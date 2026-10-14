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
            eventos += eventos_entre(antes, novo, agora - self._curando_em)
            cena = novo["cena"]
            if cena and not cena.startswith("Menu") and cena not in self.cenas:
                # chegar do menu (carregou o save) ou do nada não é explorar
                if antes is not None and not antes["cena"].startswith("Menu"):
                    eventos.append("cena_nova")
                self.cenas.add(cena)
                self._salvar_cenas()
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
