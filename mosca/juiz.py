"""O juiz de dentro do jogo: eventos lidos do próprio Hollow Knight.

O plugin mod/MoscaEventos (BepInEx) manda ~30x/s por UDP local o estado do jogo:
sala, posição, vida, geo, golpes que acertaram, inimigos mortos... Aqui a
diferença entre um estado e o seguinte vira os mesmos eventos que o LeitorHUD
tirava da tela, só que exatos, e mais dois que a tela não via:
- "inimigo_morto";
- "cena_nova": uma sala (cena do jogo) onde a mosca nunca tinha estado.

A mosca continua vendo só a tela: isto só decide o que foi bom ou ruim. Sem
pacotes há ATIVO_S segundos (jogo fechado, plugin fora), `ativo` é False e o
painel volta para a leitura pela tela.
"""

import json
import socket
import time
from pathlib import Path

import numpy as np

from .config import PASTA

PORTA = 47123
ATIVO_S = 1.0
CURA_S = 1.0  # vida que sobe até 1 s depois do Foco é cura (banco e renascer, não)
MAX_GOLPES_QUADRO = 3  # um pacote atrasado não vira uma chuva de acertos


def eventos_entre(antes, agora, curou_ha_s):
    """Eventos de um estado do jogo para o seguinte (dicts do plugin)."""
    if antes is None or antes["cena"].startswith("Menu") or agora["cena"].startswith("Menu"):
        return []  # carregando o save, os valores pulam: é só referência
    eventos = []
    if agora["morta"] and not antes["morta"]:
        return ["morte"]
    if not agora["morta"] and not antes["morta"]:
        perdeu = (antes["vida"] + antes["vida_azul"]) - (agora["vida"] + agora["vida_azul"])
        if perdeu > 0:
            eventos += ["dano"] * perdeu
        ganhou = agora["vida"] - antes["vida"]
        if ganhou > 0 and curou_ha_s <= CURA_S:
            eventos += ["cura"] * ganhou
    if agora["geo"] > antes["geo"]:  # gastar ou perder geo não é prêmio
        eventos.append("geo")
    eventos += ["acerto"] * min(MAX_GOLPES_QUADRO, max(0, agora["golpes"] - antes["golpes"]))
    eventos += ["inimigo_morto"] * min(MAX_GOLPES_QUADRO, max(0, agora["inimigos_mortos"] - antes["inimigos_mortos"]))
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
            except (BlockingIOError, InterruptedError):
                break
            try:
                novo = json.loads(dados)
            except ValueError:
                continue
            agora = time.monotonic()
            antes = self.estado if agora - self._recebido_em < ATIVO_S else None  # voltou: só referência
            if novo["curando"]:
                self._curando_em = agora
            novos = eventos_entre(antes, novo, agora - self._curando_em)
            eventos += novos
            if "morte" in novos:
                self._morreu_nesta_cena = True
            cena = novo["cena"]
            mudou = antes is not None and cena != antes["cena"]
            if cena and not cena.startswith("Menu") and cena not in self.cenas:
                # chegar do menu (carregou o save), do nada ou renascendo no banco
                # depois de morrer não é explorar
                if mudou and not antes["cena"].startswith("Menu") and not self._morreu_nesta_cena:
                    eventos.append("cena_nova")
                self.cenas.add(cena)
                self._salvar_cenas()
            if mudou:
                self._morreu_nesta_cena = False
            self.estado, self._recebido_em = novo, agora
        return eventos

    @property
    def vida(self):
        return self.estado["vida"] if self.estado else None

    def _salvar_cenas(self):
        temporario = self.arquivo_cenas.with_suffix(".tmp")
        temporario.write_text(json.dumps(sorted(self.cenas)))
        temporario.replace(self.arquivo_cenas)

    def fechar(self):
        self.sock.close()


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
    """

    PARADA_VEL, PARADA_S, PARADA_REPETE_S = 0.3, 3.0, 2.0
    PRESA_S, AVISO_S, PRESA_REPETE_S, PRESA_X, SUBIU = 6.0, 4.0, 3.0, 0.5, 2.0
    LOOP_S, LOOP_REPETE_S, ANDOU, SALDO = 15.0, 5.0, 20.0, 4.0
    LUGAR = 8.0

    def __init__(self, arquivo_lugares=PASTA / "memoria_lugares.json", dt=1 / 30):
        self.dt = dt
        self.arquivo_lugares = Path(arquivo_lugares)
        self.lugares = set()
        if self.arquivo_lugares.exists():
            self.lugares = {tuple(l) for l in json.loads(self.arquivo_lugares.read_text())}
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

    def passo(self, estado, esquerda, direita, algo_bom):
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
        if len(janela) >= int(self.LOOP_S / self.dt) and not self._espera["loop"]:
            xs = np.array([j[0] for j in janela])
            if (np.abs(np.diff(xs)).sum() > self.ANDOU and abs(xs[-1] - xs[0]) < self.SALDO
                    and not any(j[3] for j in janela)):
                eventos.append("loop")
                self._espera["loop"] = int(self.LOOP_REPETE_S / self.dt)
        return eventos

    def _salvar_lugares(self):
        temporario = self.arquivo_lugares.with_suffix(".tmp")
        temporario.write_text(json.dumps(sorted(self.lugares)))
        temporario.replace(self.arquivo_lugares)
