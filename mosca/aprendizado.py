"""Aprendizado: o modelo de imitação, o gravador de partidas e o torneio
campeã x desafiante."""

import json
import os
import threading
import time
from pathlib import Path

import numpy as np

from .config import ACOES, ARQUIVO_DESAFIANTE, ARQUIVO_MODELO, ARQUIVO_TORNEIO, PASTA_GRAVACOES
from .conectoma import CAMADAS_CONECTOMA, RedeConectoma
from .olho import cinza, tamanho_entrada


class Imitacao:
    """O cérebro treinado: olho -> ... -> zonas de comando. Duas arquiteturas:

    - "mlp": rede pequena olho -> 64 interneurônios inventados -> teclas;
    - "conectoma": a fiação real da mosca (ver mosca/conectoma.py).

    Treinado pelo `treinar.py` com as partidas gravadas (suas e da mosca).
    """

    def __init__(self, pesos):
        self.arquitetura = str(pesos["arquitetura"]) if "arquitetura" in pesos else "mlp"
        if self.arquitetura == "conectoma":
            nomes = ["A", "a", "bc", "bd", "R", "r", *CAMADAS_CONECTOMA]
            self.rede = RedeConectoma({k: pesos[k] for k in nomes})
            self.w1 = pesos["A"]  # entrada: confere o olho abaixo
            self.grupos = {k: pesos[f"grupos_{k}"] for k in ("visual", "central", "descendente")}
        else:
            self.w1, self.b1 = pesos["w1"], pesos["b1"]
            self.w2, self.b2 = pesos["w2"], pesos["b2"]
        self.media, self.desvio = pesos["media"], pesos["desvio"]
        self.acoes = [str(a) for a in pesos["acoes"]]
        self.n_quadros = int(pesos["n_quadros"])
        self.metodo = str(pesos["metodo"]) if "metodo" in pesos else "imitação"
        # Modelos de antes do olho v2 não guardam a versão: são do olho 1
        self.versao_olho = int(pesos["versao_olho"]) if "versao_olho" in pesos else 1
        if self.w1.shape[0] != tamanho_entrada(self.versao_olho):
            raise ValueError(f"o modelo não bate com o olho versão {self.versao_olho}")
        self.treino_id = None  # número do treino no Supabase, se foi registrado
        self.papel = None  # "campeã" ou "desafiante", quando está num torneio

    @classmethod
    def carregar(cls, arquivo=ARQUIVO_MODELO):
        if not Path(arquivo).exists():
            return None
        with np.load(arquivo) as pesos:
            modelo = cls({k: pesos[k] for k in pesos.files})
        info = Path(arquivo).with_suffix(".json")  # escrito pelo treinar.py
        if info.exists():
            modelo.treino_id = json.loads(info.read_text()).get("treino_id")
        return modelo

    def interneuronios(self, x):
        return np.maximum(0, ((x - self.media) / self.desvio) @ self.w1 + self.b1)

    def atividades(self, x):
        """Atividade de cada camada (conectoma: visual, central, descendente) e as
        probabilidades das teclas. O painel acende os neurônios reais com isto."""
        if self.arquitetura == "conectoma":
            f = self.rede.frente((x - self.media) / self.desvio)
            return {"visual": f["v"], "central": f["c2"], "descendente": f["d"], "prob": f["prob"]}
        z = self.interneuronios(x) @ self.w2 + self.b2
        return {"prob": 1 / (1 + np.exp(-np.clip(z, -30, 30)))}

    def prever(self, x):
        """Probabilidade de cada tecla estar apertada, na ordem de self.acoes."""
        return self.atividades(x)["prob"]


class Gravador:
    """Guarda (tela reduzida, teclas apertadas) enquanto alguém joga: você
    (gravacoes/) ou a mosca sozinha (gravacoes_mosca/).

    Salva em <pasta>/<data>/parte_NNN.npz a cada QUADROS_POR_PARTE quadros,
    numa thread, para não travar o painel. As telas vão em tons de cinza:
    o olho não usa cor e o arquivo fica 3x menor (~8 KB por quadro).
    """

    QUADROS_POR_PARTE = 900  # ~30 s

    def __init__(self, base=PASTA_GRAVACOES):
        nome = time.strftime("%Y-%m-%d_%H%M%S")
        self.pasta = base / nome
        n = 2
        while self.pasta.exists():  # duas gravações no mesmo segundo
            self.pasta, n = base / f"{nome}_{n}", n + 1
        self.pasta.mkdir(parents=True)
        self.inicio = time.monotonic()
        self.total = 0
        self._parte = 0
        self._telas, self._teclas = [], []
        self._recompensas, self._vidas = [], []
        self._salvando = []

    def adicionar(self, reduzida, teclas, recompensa=0.0, vida=None):
        """`recompensa` e `vida` vêm do HUD; ficam guardadas para o aprendizado
        por reforço no futuro (o treino de imitação não usa)."""
        self._telas.append(cinza(reduzida))
        self._teclas.append(teclas)
        self._recompensas.append(recompensa)
        self._vidas.append(-1 if vida is None else vida)
        self.total += 1
        if len(self._telas) >= self.QUADROS_POR_PARTE:
            self._salvar()

    def _salvar(self):
        if not self._telas:
            return
        arquivo = self.pasta / f"parte_{self._parte:03d}.npz"
        telas, teclas = np.stack(self._telas), np.stack(self._teclas)
        recompensas = np.array(self._recompensas, dtype=np.float32)
        vidas = np.array(self._vidas, dtype=np.int8)
        self._telas, self._teclas = [], []
        self._recompensas, self._vidas = [], []
        self._parte += 1
        t = threading.Thread(
            target=np.savez_compressed,
            args=(arquivo,),
            kwargs=dict(
                telas=telas, teclas=teclas, recompensas=recompensas, vidas=vidas,
                acoes=np.array(ACOES),
            ),
        )
        t.start()
        self._salvando.append(t)

    def parar(self):
        self._salvar()
        for t in self._salvando:
            t.join()
        if self.total == 0:
            self.pasta.rmdir()


class Torneio:
    """Campeã x desafiante: a mosca só troca de cérebro quando o novo prova que
    joga melhor.

    Todo treino gera uma desafiante (modelo_desafiante.npz); a campeã
    (modelo_mosca.npz) segue sendo a versão que joga. Com o "Controlar jogo"
    ligado, as duas se alternam em rodadas de RODADA_S; cada rodada é uma
    amostra de recompensa por minuto. Com MINIMO_S e MINIMO_RODADAS de cada:
    - a desafiante vira campeã se fizer mais de MARGEM a mais E a diferença for
      maior que 2x a incerteza (variação entre rodadas): não ganha por sorte;
    - é descartada se fizer MARGEM a menos, ou se chegar a MAXIMO_S sem vencer.
    Na dúvida, a campeã fica. Descartada, continua guardada no Supabase.
    """

    RODADA_S = 60
    RODADA_MINIMA_S = 20  # rodada interrompida mais curta que isto não vira amostra
    MINIMO_S = 240
    MINIMO_RODADAS = 3
    MAXIMO_S = 900
    MARGEM = 0.5  # de recompensa por minuto
    PAPEIS = ("campea", "desafiante")

    def __init__(self, arquivo=ARQUIVO_TORNEIO, campea=ARQUIVO_MODELO, desafiante=ARQUIVO_DESAFIANTE):
        self.arquivo, self.campea, self.desafiante = Path(arquivo), Path(campea), Path(desafiante)
        self.estado = {"placar": self._placar_zerado(), "vez": "desafiante",
                       "rodada": self._rodada_zerada(), "rodadas": self._rodadas_zeradas(),
                       "mosca_desde_treino": 0.0}
        if self.arquivo.exists():
            self.estado.update(json.loads(self.arquivo.read_text()))
        # Desafiante treinada fora do painel (treinar.py à mão): o placar era de outra
        if self.em_disputa and self.estado.get("desafiante_id") != self._id_desafiante():
            self._zerar_disputa()
            self.salvar()

    def _placar_zerado(self):
        return {papel: {"segundos": 0.0, "recompensa": 0.0} for papel in self.PAPEIS}

    def _rodada_zerada(self):
        return {"segundos": 0.0, "recompensa": 0.0}

    def _rodadas_zeradas(self):
        return {papel: [] for papel in self.PAPEIS}  # recompensa/min de cada rodada

    def _id_desafiante(self):
        """Número (ou data) da desafiante, pelo arquivo de informação do treino."""
        info = self.desafiante.with_suffix(".json")
        if not info.exists():
            return None
        dados = json.loads(info.read_text())
        return dados.get("treino_id") or info.stat().st_mtime

    def _zerar_disputa(self):
        self.estado.update(placar=self._placar_zerado(), vez="desafiante",
                           rodada=self._rodada_zerada(), rodadas=self._rodadas_zeradas(),
                           desafiante_id=self._id_desafiante())

    def salvar(self):
        self.arquivo.write_text(json.dumps(self.estado))

    @property
    def em_disputa(self):
        return self.desafiante.exists() and self.campea.exists()

    def nova_desafiante(self):
        """Uma desafiante acabou de ser treinada. Sem campeã ainda, ela já assume."""
        self._zerar_disputa()
        self.salvar()
        if not self.campea.exists():
            self._promover()
            return "primeira versão treinada: já é a campeã"
        return None

    def quem_joga(self):
        return self.estado["vez"] if self.em_disputa else "campea"

    def contar(self, papel, segundos, recompensa):
        """Um quadro de jogo da mosca. Devolve True quando é hora de trocar de versão."""
        self.estado["mosca_desde_treino"] += segundos
        if not self.em_disputa:
            return False
        for acumulado in (self.estado["placar"][papel], self.estado["rodada"]):
            acumulado["segundos"] += segundos
            acumulado["recompensa"] += recompensa
        if self.estado["rodada"]["segundos"] >= self.RODADA_S:
            self.fechar_rodada(papel)
            self.estado["vez"] = "campea" if papel == "desafiante" else "desafiante"
            self.salvar()
            return True
        return False

    def fechar_rodada(self, papel):
        """Fim de rodada (ou o controle foi desligado no meio): vira uma amostra."""
        r = self.estado["rodada"]
        if r["segundos"] >= self.RODADA_MINIMA_S:
            self.estado["rodadas"][papel].append(r["recompensa"] / r["segundos"] * 60)
        self.estado["rodada"] = self._rodada_zerada()
        self.salvar()

    def incerteza(self):
        """Erro padrão da diferença de recompensa/min, pela variação entre rodadas."""
        variancia = 0.0
        for papel in self.PAPEIS:
            amostras = self.estado["rodadas"][papel]
            if len(amostras) < 2:
                return float("inf")
            variancia += np.var(amostras, ddof=1) / len(amostras)
        return float(np.sqrt(variancia))

    def por_minuto(self, papel):
        p = self.estado["placar"][papel]
        return p["recompensa"] / p["segundos"] * 60 if p["segundos"] else 0.0

    def veredito(self):
        """None (ainda disputando), "venceu" ou "perdeu" (para a desafiante)."""
        if not self.em_disputa:
            return None
        tempos = [self.estado["placar"][p]["segundos"] for p in self.PAPEIS]
        rodadas = [len(self.estado["rodadas"][p]) for p in self.PAPEIS]
        if min(tempos) < self.MINIMO_S or min(rodadas) < self.MINIMO_RODADAS:
            return None
        diferenca = self.por_minuto("desafiante") - self.por_minuto("campea")
        if diferenca > self.MARGEM and diferenca > 2 * self.incerteza():
            return "venceu"
        if diferenca < -self.MARGEM or min(tempos) >= self.MAXIMO_S:
            return "perdeu"
        return None

    def encerrar(self, resultado):
        """Aplica o veredito: promove ou descarta a desafiante."""
        if resultado == "venceu":
            self._promover()
        else:
            for arquivo in (self.desafiante, self.desafiante.with_suffix(".json")):
                arquivo.unlink(missing_ok=True)
        self._zerar_disputa()
        self.salvar()

    def _promover(self):
        info = self.desafiante.with_suffix(".json")
        if info.exists():
            os.replace(info, self.campea.with_suffix(".json"))
        os.replace(self.desafiante, self.campea)

    def ciclo_cumprido(self, segundos):
        return self.estado["mosca_desde_treino"] >= segundos

    def zerar_ciclo(self):
        self.estado["mosca_desde_treino"] = 0.0
        self.salvar()
