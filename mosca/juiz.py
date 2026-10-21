"""O juiz de dentro do jogo: eventos lidos do próprio Hollow Knight.

O plugin mod/MoscaEventos (BepInEx) manda ~30x/s por UDP local o estado do jogo:
sala, posição, vida, geo, golpes que acertaram, inimigos mortos... Aqui a
diferença entre um estado e o seguinte vira os mesmos eventos que o LeitorHUD
tirava da tela, só que exatos, e mais dois que a tela não via:
- "inimigo_morto";
- "cena_nova": uma sala (cena do jogo) onde a mosca nunca tinha estado.

Com o plugin novo, também:
- "dano_chefe": cada 1% da vida de um chefe tirado;
- "sombra_recuperada": matou a sombra (o geo da última morte voltou);
- "inimigo_repetido": no lugar de "inimigo_morto" quando é o mesmo inimigo (cena
  e nome do objeto) que ela já tinha matado e renasceu.

A mosca continua vendo só a tela: isto só decide o que foi bom ou ruim. Sem
pacotes há ATIVO_S segundos (jogo fechado, plugin fora), `ativo` é False e o
painel volta para a leitura pela tela.
"""

import collections
import json
import socket
import time
from pathlib import Path

import numpy as np

from .config import PASTA

PORTA = 47123
ATIVO_S = 1.0
CURA_S = 1.0  # vida que sobe até 1 s depois do Foco é cura (banco e renascer, não)
VIDA_BAIXA = 2  # máscaras: curar com isto ou menos é "cura crítica"
MAGIA_ALMA = 20  # alma gasta de uma vez (sem curar) que é uma magia (custa 33, ou 24 com amuleto)
MAGIA_ALVO_S = 1.0  # a magia que não acertou nada neste tempo foi "sem alvo"
MAX_GOLPES_QUADRO = 3
# Vai e volta pela mesma passagem: em PASSAGEM_S, PASSAGEM_VEZES trocas entre as
# mesmas duas salas (A->B->A->B->A) sem nada de bom no meio
PASSAGEM_S, PASSAGEM_VEZES = 90.0, 4
MAX_DANO_CHEFE = 20  # % de chefe por pacote (um golpe forte tira uns 10%)
BONS = {"inimigo_morto", "chefe_derrotado", "dano_chefe", "sombra_recuperada", "cena_nova", "banco_novo", "geo", "acerto", "cura"}  # um pacote atrasado não vira uma chuva de acertos


def eventos_entre(antes, agora, curou_ha_s):
    """Eventos de um estado do jogo para o seguinte (dicts do plugin)."""
    if antes is None or antes["cena"].startswith("Menu") or agora["cena"].startswith("Menu"):
        return []  # carregando o save, os valores pulam: é só referência
    eventos = []
    if agora["morta"] and not antes["morta"]:
        return ["morte"]
    if agora.get("derrotas", 0) > antes.get("derrotas", 0):  # perdeu no Salão dos Deuses
        return ["morte"]
    if not agora["morta"] and not antes["morta"]:
        perdeu = (antes["vida"] + antes["vida_azul"]) - (agora["vida"] + agora["vida_azul"])
        if perdeu > 0:
            eventos += ["dano"] * perdeu
        ganhou = agora["vida"] - antes["vida"]
        if ganhou > 0 and curou_ha_s <= CURA_S:
            eventos += ["cura"] * ganhou
            if antes["vida"] <= VIDA_BAIXA:  # curar quando importa vale mais
                eventos.append("cura_critica")
    # magia: a alma cai de uma vez, sem estar curando (o Foco gasta aos poucos)
    if (not agora["morta"] and not antes["curando"] and not agora["curando"] and agora["cena"] == antes["cena"]
            and antes.get("alma", 0) - agora.get("alma", 0) >= MAGIA_ALMA):
        eventos.append("magia")
        if antes["vida"] <= VIDA_BAIXA and antes["vida"] < antes.get("vida_max", 99):
            eventos.append("magia_com_vida_baixa")
    if agora.get("perigo") and not antes.get("perigo"):  # caiu em espinhos ou ácido
        eventos.append("perigo")
    if agora["geo"] > antes["geo"]:  # gastar ou perder geo não é prêmio
        eventos.append("geo")
    eventos += ["acerto"] * min(MAX_GOLPES_QUADRO, max(0, agora["golpes"] - antes["golpes"]))
    eventos += ["inimigo_morto"] * min(MAX_GOLPES_QUADRO, max(0, agora["inimigos_mortos"] - antes["inimigos_mortos"]))
    chefes = agora.get("chefes_derrotados", 0) - antes.get("chefes_derrotados", 0)
    eventos += ["chefe_derrotado"] * min(MAX_GOLPES_QUADRO, max(0, chefes))
    # em milésimos de chefe: um evento a cada 10 (1%), sem perder o resto entre pacotes
    pct = agora.get("dano_chefe", 0) // 10 - antes.get("dano_chefe", 0) // 10
    eventos += ["dano_chefe"] * min(MAX_DANO_CHEFE, max(0, pct))
    if antes.get("sombra") and agora.get("sombra") is False and not agora["morta"]:
        eventos.append("sombra_recuperada")
    return eventos


class JuizDoJogo:
    def __init__(self, arquivo_cenas=PASTA / "memoria_cenas.json", porta=PORTA):
        self.arquivo_cenas = Path(arquivo_cenas)
        self.cenas = set(json.loads(self.arquivo_cenas.read_text())) if self.arquivo_cenas.exists() else set()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", porta))
        self.sock.setblocking(False)
        self.estado = None  # último estado lido
        self._recebido_em = float("-inf")
        self._curando_em = float("-inf")
        self._morreu_nesta_cena = False  # a próxima troca de sala é renascer no banco
        self._trocas = []  # (quando, sala de onde, sala para onde): o vai e volta
        self._bom_em = float("-inf")
        self.vx_ao_entrar = 0.0  # direção em que entrou na sala atual (reflexo de seguir em frente)
        self.arquivo_bancos = self.arquivo_cenas.with_name("memoria_bancos.json")
        self.bancos = set(json.loads(self.arquivo_bancos.read_text())) if self.arquivo_bancos.exists() else set()
        self.arquivo_inimigos = self.arquivo_cenas.with_name("memoria_inimigos.json")
        self.inimigos = set(json.loads(self.arquivo_inimigos.read_text())) if self.arquivo_inimigos.exists() else set()
        self._ultimo_abate = None  # número do último abate já visto (o plugin numera)
        self._magias = []  # (quando, golpes até ali): esperando ver se acertaram

    @property
    def ativo(self):
        return (time.monotonic() - self._recebido_em < ATIVO_S and self.estado is not None
                and not self.estado["cena"].startswith("Menu"))

    def passo(self):
        """Lê o que chegou desde o último quadro. Devolve os eventos."""
        eventos = []
        while True:
            try:
                dados = self.sock.recv(4096)
            except OSError:  # nada mais na fila (ou fechado: painel saindo)
                break
            try:
                novo = json.loads(dados)
            except ValueError:
                continue
            agora = time.monotonic()
            antes = self.estado if agora - self._recebido_em < ATIVO_S else None  # voltou: só referência
            if novo["curando"]:
                self._curando_em = agora
            novos = self._repetidos(antes, novo, eventos_entre(antes, novo, agora - self._curando_em))
            novos += self._magias_sem_alvo(agora, novo, "magia" in novos)
            eventos += novos
            if BONS.intersection(novos):
                self._bom_em = agora
            if "morte" in novos:
                self._morreu_nesta_cena = True
            cena = novo["cena"]
            mudou = antes is not None and cena != antes["cena"]
            if cena and not cena.startswith("Menu") and cena not in self.cenas:
                # chegar do menu (carregou o save), do nada ou renascendo no banco
                # depois de morrer não é explorar
                if mudou and not antes["cena"].startswith("Menu") and not self._morreu_nesta_cena:
                    eventos.append("cena_nova")
                    self._bom_em = agora
                self.cenas.add(cena)
                self._salvar_cenas()
            if mudou and not antes["cena"].startswith("Menu") and not self._morreu_nesta_cena:
                eventos += self._vai_e_volta(agora, antes["cena"], cena)
                self.vx_ao_entrar = novo["vx"]
            if mudou:
                self._morreu_nesta_cena = False
            # banco novo: o ponto de retorno mudou para um nunca visto (descansou nele).
            # Carregar o save só registra o banco em que está
            banco = novo.get("banco", "")
            if banco and banco != "|" and banco not in self.bancos:
                if antes is not None and not antes["cena"].startswith("Menu") and banco != antes.get("banco"):
                    eventos.append("banco_novo")
                    self._bom_em = agora
                self.bancos.add(banco)
                self._salvar(self.arquivo_bancos, self.bancos)
            self.estado, self._recebido_em = novo, agora
        return eventos

    def _magias_sem_alvo(self, agora, novo, soltou):
        """Uma magia que não acertou nada em MAGIA_ALVO_S vira "magia_sem_alvo"."""
        golpes = novo.get("golpes", 0)
        if soltou:
            self._magias.append((agora, golpes))
        saida = []
        while self._magias and agora - self._magias[0][0] >= MAGIA_ALVO_S:
            _, antes = self._magias.pop(0)
            if golpes <= antes:
                saida.append("magia_sem_alvo")
        if any(golpes > g for _, g in self._magias):  # acertou: as pendentes antes dela valem
            self._magias = [m for m in self._magias if golpes <= m[1]]
        return saida

    def _repetidos(self, antes, novo, eventos):
        """Troca "inimigo_morto" por "inimigo_repetido" nos inimigos que ela já
        tinha matado (cena + nome do objeto, que o plugin manda nos últimos abates)."""
        abates = novo.get("mortos")
        if abates is None:  # plugin antigo
            return eventos
        if self._ultimo_abate is None or (abates and abates[-1][0] < self._ultimo_abate):
            self._ultimo_abate = 0  # primeiro pacote ou o jogo reabriu: a contagem recomeça
        if antes is None:  # só referência
            self._ultimo_abate = abates[-1][0] if abates else 0
            return eventos
        novos = [nome for n, nome in abates if n > self._ultimo_abate]
        if abates:
            self._ultimo_abate = abates[-1][0]
        if not novos:
            return eventos
        eventos = list(eventos)
        for nome in novos[-eventos.count("inimigo_morto"):] if "inimigo_morto" in eventos else []:
            chave = f"{novo['cena']}|{nome}"
            if chave in self.inimigos:
                eventos[eventos.index("inimigo_morto")] = "inimigo_repetido"
            self.inimigos.add(chave)
        self._salvar(self.arquivo_inimigos, self.inimigos)
        return eventos

    def _vai_e_volta(self, agora, de, para):
        """Uma troca de sala. Devolve ["vai_e_volta"] se ela anda indo e voltando
        pela mesma passagem sem ganhar nada com isso."""
        self._trocas = [t for t in self._trocas if agora - t[0] < PASSAGEM_S and t[0] > self._bom_em]
        self._trocas.append((agora, de, para))
        par = {de, para}
        mesmas = [t for t in self._trocas if {t[1], t[2]} == par]
        if len(mesmas) >= PASSAGEM_VEZES:
            self._trocas = mesmas[-(PASSAGEM_VEZES - 2):]  # punir de novo só depois de mais um vai e volta
            return ["vai_e_volta"]
        return []

    @property
    def vida(self):
        return self.estado["vida"] if self.estado else None

    def _salvar_cenas(self):
        self._salvar(self.arquivo_cenas, self.cenas)

    @staticmethod
    def _salvar(arquivo, conjunto):
        temporario = arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(sorted(conjunto)))
        temporario.replace(arquivo)

    def fechar(self):
        self.sock.close()


def eh_arena(cena):
    """Arena de luta do Salão dos Deuses (as salas de passagem dele não contam)."""
    return cena.startswith("GG_") and cena not in ("GG_Workshop", "GG_Atrium", "GG_Atrium_Roof")


class MemoriaDePerigos:
    """Onde ela já caiu em espinhos ou ácido: a borda (o último ponto em chão
    firme antes da queda) e o lado para onde ia. Fica salva e vale entre sessões.

    Perto de uma borda conhecida (até MARGEM antes dela, na mesma altura), andar
    ou esquivar para o lado dela é vetado: o reflexo de uma mosca na beira de um
    abismo. As gravações guardam as teclas que de fato foram ao jogo, então o
    treino aprende com ela parando na borda.
    """

    MARGEM, ALEM, ALTURA = 2.0, 0.5, 2.5  # unidades do jogo (ela anda ~8 por segundo)
    JUNTAR = 1.0  # quedas pela mesma borda: uma só
    HISTORICO_S = 2.0
    MAXIMO = 1000

    def __init__(self, arquivo=PASTA / "memoria_perigos.json", dt=1 / 30):
        self.arquivo = Path(arquivo)
        self.bordas = json.loads(self.arquivo.read_text()) if self.arquivo.exists() else []
        self._hist = collections.deque(maxlen=int(self.HISTORICO_S / dt))

    def passo(self, estado, eventos):
        """Um quadro do juiz: guarda por onde ela anda e, se caiu, a borda."""
        if estado is None:
            return
        if "perigo" in eventos:
            self._lembrar(estado)
        self._hist.append((estado["cena"], estado["x"], estado["y"], estado["no_chao"]))

    def _lembrar(self, estado):
        firmes = [h for h in self._hist if h[0] == estado["cena"] and h[3]]
        if not firmes:
            return
        cena, x, y, _ = firmes[-1]
        if abs(estado["x"] - x) < 0.3:  # caiu de cima, sem andar para uma borda
            return
        lado = 1 if estado["x"] > x else -1
        for borda in self.bordas:
            if borda[0] == cena and borda[3] == lado and abs(borda[1] - x) < self.JUNTAR and abs(borda[2] - y) < self.JUNTAR:
                borda[1] = round(min(borda[1], x) if lado > 0 else max(borda[1], x), 2)  # a mais cautelosa
                break
        else:
            self.bordas.append([cena, round(x, 2), round(y, 2), lado])
            self.bordas = self.bordas[-self.MAXIMO:]
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(self.bordas))
        temporario.replace(self.arquivo)

    def vetar(self, estado):
        """Ações a não apertar agora (vazio longe das bordas conhecidas)."""
        if estado is None or estado["morta"]:
            return set()
        vetadas = set()
        for cena, x, y, lado in self.bordas:
            if cena != estado["cena"] or abs(estado["y"] - y) > self.ALTURA:
                continue
            if -self.ALEM < (x - estado["x"]) * lado < self.MARGEM:
                vetadas |= {"Direita" if lado > 0 else "Esquerda", "Esquiva"}
        return vetadas


class DetectoresPelaPosicao:
    """Parada, presa, andando em círculos e lugar novo pela posição real do
    Cavaleiro (unidades do jogo; ele anda ~8/s), no lugar das estimativas pela
    câmera quando o plugin está mandando. Mesmos tempos dos detectores da tela.

    - parada: velocidade < PARADA_VEL por PARADA_S (não curando); repete a cada 2 s
    - presa: forçando um lado >= 70% do tempo e x quase não muda (< PRESA_X) em
      PRESA_S; aviso (`encostada`, sem punir) com AVISO_S. Subindo de verdade
      (y mudou > SUBIU) é escalada, não presa
    - loop: em LOOP_S andou > ANDOU na horizontal mas o saldo é < SALDO, sem
      nada de bom no meio
    - lugar_novo: um pedaço (LUGAR x LUGAR) de uma sala onde nunca esteve
    - sem_novidade: SEM_NOVIDADE_S sem lugar, sala ou banco novo, e sem lutar há
      COMBATE_S; repete a cada SEM_NOVIDADE_REPETE_S. Não conta no Salão dos
      Deuses (cenas GG_*), onde ela luta sem explorar
    - loop também não conta nas arenas do Salão dos Deuses: lá ir e voltar no
      mesmo chão é lutar, e a punição a empurrava para os espinhos das bordas
    """

    PARADA_VEL, PARADA_S, PARADA_REPETE_S = 0.3, 3.0, 2.0
    PRESA_S, AVISO_S, PRESA_REPETE_S, PRESA_X, SUBIU = 6.0, 4.0, 3.0, 0.5, 2.0
    LOOP_S, LOOP_REPETE_S, ANDOU, SALDO = 15.0, 5.0, 20.0, 4.0
    LUGAR = 8.0
    SEM_NOVIDADE_S, SEM_NOVIDADE_REPETE_S, COMBATE_S = 60.0, 15.0, 10.0
    NOVIDADES = {"lugar_novo", "cena_nova", "banco_novo", "sala_nova", "sombra_recuperada", "chefe_derrotado"}
    COMBATE = {"acerto", "dano", "inimigo_morto", "dano_chefe", "chefe_derrotado"}

    def __init__(self, arquivo_lugares=PASTA / "memoria_lugares.json", dt=1 / 30):
        self.dt = dt
        self.arquivo_lugares = Path(arquivo_lugares)
        self.lugares = set()
        if self.arquivo_lugares.exists():
            self.lugares = {tuple(l) for l in json.loads(self.arquivo_lugares.read_text())}
        # não recomeçam com a sala nem com a morte: entrar numa sala conhecida não é novidade
        self._sem_novidade = self._sem_luta = self._espera_novidade = 0
        self.reiniciar()

    def reiniciar(self):
        self._hist = []  # (x, y, lado -1/0/1, algo bom)
        self._parada = 0
        self._espera = {"parada": 0, "presa": 0, "aviso": 0, "loop": 0}
        self._cena = None
        self.lado = None
        self.encostada = False

    def _janela(self, segundos):
        return self._hist[-int(segundos / self.dt):]

    def passo(self, estado, esquerda, direita, algo_bom, eventos_jogo=()):
        """`eventos_jogo`: os eventos do juiz neste quadro (novidade e luta)."""
        if estado is None or estado["morta"]:
            self.reiniciar()
            return []
        if estado["cena"] != self._cena:  # sala nova: a posição recomeça
            self.reiniciar()
            self._cena = estado["cena"]
        for k in self._espera:
            self._espera[k] = max(0, self._espera[k] - 1)
        x, y = estado["x"], estado["y"]
        self._hist.append((x, y, 1 if direita and not esquerda else -1 if esquerda and not direita else 0, algo_bom))
        self._hist = self._janela(max(self.LOOP_S, self.PRESA_S))
        eventos = []

        lugar = (estado["cena"], int(x // self.LUGAR), int(y // self.LUGAR))
        if lugar not in self.lugares:
            self.lugares.add(lugar)
            self._salvar_lugares()
            eventos.append("lugar_novo")
        eventos += self._sem_novidade_passo(estado, set(eventos_jogo) | set(eventos))

        parada = abs(estado["vx"]) < self.PARADA_VEL and abs(estado["vy"]) < self.PARADA_VEL
        self._parada = self._parada + 1 if parada and not estado["curando"] else 0
        if self._parada * self.dt >= self.PARADA_S and not self._espera["parada"]:
            eventos.append("parada")
            self._espera["parada"] = int(self.PARADA_REPETE_S / self.dt)

        for segundos, chave in ((self.AVISO_S, "aviso"), (self.PRESA_S, "presa")):
            janela = self._janela(segundos)
            if len(janela) < int(segundos / self.dt) or self._espera[chave]:
                continue
            xs, ys, lados = (np.array(c) for c in list(zip(*janela))[:3])
            forcando = max((lados == 1).mean(), (lados == -1).mean())
            if forcando >= 0.7 and np.ptp(xs) < self.PRESA_X and abs(ys[-1] - ys[0]) <= self.SUBIU:
                self.lado = "Direita" if (lados == 1).mean() >= (lados == -1).mean() else "Esquerda"
                self._espera[chave] = int(self.PRESA_REPETE_S / self.dt)
                if chave == "aviso":
                    self.encostada = True
                else:
                    eventos.append("presa")

        janela = self._janela(self.LOOP_S)
        if (len(janela) >= int(self.LOOP_S / self.dt) and not self._espera["loop"]
                and not eh_arena(estado["cena"])):
            xs = np.array([j[0] for j in janela])
            if (np.abs(np.diff(xs)).sum() > self.ANDOU and abs(xs[-1] - xs[0]) < self.SALDO
                    and not any(j[3] for j in janela)):
                eventos.append("loop")
                self._espera["loop"] = int(self.LOOP_REPETE_S / self.dt)
        return eventos

    def _sem_novidade_passo(self, estado, eventos):
        if self.NOVIDADES & eventos or estado["cena"].startswith("GG_"):
            self._sem_novidade = 0
        else:
            self._sem_novidade += 1
        self._sem_luta = 0 if self.COMBATE & eventos else self._sem_luta + 1
        self._espera_novidade = max(0, self._espera_novidade - 1)
        if (self._sem_novidade * self.dt >= self.SEM_NOVIDADE_S and self._sem_luta * self.dt >= self.COMBATE_S
                and not self._espera_novidade):
            self._espera_novidade = int(self.SEM_NOVIDADE_REPETE_S / self.dt)
            return ["sem_novidade"]
        return []

    def _salvar_lugares(self):
        temporario = self.arquivo_lugares.with_suffix(".tmp")
        temporario.write_text(json.dumps(sorted(self.lugares)))
        temporario.replace(self.arquivo_lugares)
