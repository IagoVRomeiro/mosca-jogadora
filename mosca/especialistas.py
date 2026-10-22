"""Especialistas por chefe: um cérebro para cada arena do Salão dos Deuses.

Um cérebro só (64 interneurônios na rede inventada) para mais de 40 chefes
aprende um e esquece parte do outro. Cada arena ganha uma versão própria, que
parte da campeã geral (ou do especialista anterior) e é afinada só com as lutas
daquela arena, suas e dela (treinar.py --especialista CENA).

- Treino: a cada LUTAS_PARA_TREINAR lutas da arena sem candidato pendente.
- Avaliação: o candidato reveza as lutas com quem jogava antes (o especialista
  atual, ou a versão geral), até ter LUTAS_AVALIACAO lutas. Assume se vencer pelo
  menos tanto quanto o rival nesse mesmo período (com menos de 3 lutas do rival, a
  referência são as últimas dele antes); senão, é descartado. E é descartado na
  hora em que não tiver mais como alcançar o rival, para o melhor voltar a jogar.
  Até 21/10 o candidato jogava todas as lutas da avaliação: o especialista da
  Gruz Mother que vencia 7 de 10 ficou de fora enquanto um candidato perdia 6 de 6.
- No jogo: dentro da arena joga o especialista; fora dela, a campeã ou a
  desafiante geral, como sempre.

Arquivos em especialistas/: <cena>.npz (o atual) e <cena>.candidato.npz, cada um
com o .json do treino. O estado (lutas de cada um) fica em especialistas/estado.json.
"""

import json
import shutil
from pathlib import Path

from .config import PASTA

PASTA_ESPECIALISTAS = PASTA / "especialistas"


class Especialistas:
    LUTAS_PARA_TREINAR = 10
    LUTAS_AVALIACAO = 10

    def __init__(self, pasta=PASTA_ESPECIALISTAS, carregar=None):
        self.pasta = Path(pasta)
        self.arquivo_estado = self.pasta / "estado.json"
        self.estado = json.loads(self.arquivo_estado.read_text()) if self.arquivo_estado.exists() else {}
        self._carregar = carregar  # Imitacao.carregar (injetado: os testes não carregam redes)
        self._modelos = {}  # arquivo -> (mtime, modelo)

    def _da_arena(self, cena):
        return self.estado.setdefault(cena, {"lutas": {"atual": [], "candidato": [], "geral": []},
                                             "desde_treino": 0})

    def arquivo(self, cena, quem):
        return self.pasta / (f"{cena}.npz" if quem == "atual" else f"{cena}.candidato.npz")

    def quem_joga(self, cena):
        """'candidato' (na vez dele, em avaliação), 'atual' ou None (a versão geral)."""
        atual = "atual" if self.arquivo(cena, "atual").exists() else None
        if self.arquivo(cena, "candidato").exists():
            vez = self.estado.get(cena, {}).get("vez", "candidato")
            return "candidato" if vez == "candidato" else atual
        return atual

    def modelo(self, cena):
        """(modelo, quem) do especialista desta arena, ou (None, None)."""
        quem = self.quem_joga(cena)
        if quem is None or self._carregar is None:
            return None, None
        caminho = self.arquivo(cena, quem)
        mtime = caminho.stat().st_mtime
        guardado = self._modelos.get(caminho)
        if guardado is None or guardado[0] != mtime:
            try:
                guardado = (mtime, self._carregar(caminho))
            except Exception as e:  # arquivo pela metade, olho de outra versão...
                print(f"⚠ especialista de {cena} não carregou ({e}): joga a versão geral")
                return None, None
            self._modelos[caminho] = guardado
        return guardado[1], quem

    def registrar_luta(self, cena, quem, venceu):
        """Uma luta nesta arena terminou, jogada por `quem` ('atual', 'candidato'
        ou 'geral'). Devolve avisos (o candidato assumiu ou foi descartado)."""
        a = self._da_arena(cena)
        lutas = a["lutas"]
        resultado = 1 if venceu else 0
        lutas.setdefault(quem, []).append(resultado)
        avaliando = self.arquivo(cena, "candidato").exists()
        if avaliando and quem != "candidato":  # o rival do candidato, no mesmo período
            lutas.setdefault("rival", []).append(resultado)
        for k in lutas:
            del lutas[k][:-max(self.LUTAS_AVALIACAO, self.LUTAS_PARA_TREINAR)]
        a["desde_treino"] += 1
        avisos = []
        if avaliando:
            a["vez"] = "rival" if quem == "candidato" else "candidato"  # revezam
            veredito = self._veredito(cena)
            if veredito:
                avisos.append(veredito)
        self.salvar()
        return avisos

    def _alvo(self, cena):
        """Quantas vitórias em LUTAS_AVALIACAO o candidato precisa: as do rival no
        mesmo período (com 3+ lutas), senão as do rival antes da avaliação."""
        lutas = self.estado[cena]["lutas"]
        rival = lutas.get("rival", [])
        if len(rival) < 3:
            rival = (lutas["atual"] if self.arquivo(cena, "atual").exists() else lutas["geral"])[-self.LUTAS_AVALIACAO:]
        return sum(rival) / len(rival) * self.LUTAS_AVALIACAO if rival else 0

    def _veredito(self, cena):
        """Decide o candidato quando ele completa a avaliação, ou antes, se ele já
        não tem como alcançar o rival. Devolve o aviso, ou None (ainda avaliando)."""
        a = self.estado[cena]
        lutas = a["lutas"]
        feitas = lutas["candidato"][-self.LUTAS_AVALIACAO:]
        candidato, faltam = sum(feitas), self.LUTAS_AVALIACAO - len(feitas)
        alvo = self._alvo(cena)
        if faltam > 0 and candidato + faltam >= alvo:
            return None
        cand = self.arquivo(cena, "candidato")
        nome = cena.removeprefix("GG_")
        if faltam <= 0 and candidato >= alvo:
            atual = self.arquivo(cena, "atual")
            for origem, destino in ((cand, atual), (cand.with_suffix(".json"), atual.with_suffix(".json"))):
                if origem.exists():
                    origem.replace(destino)
            lutas["atual"] = list(lutas["candidato"])
            texto = f"🎯 Especialista de {nome} assumiu: {candidato}/{self.LUTAS_AVALIACAO} vitórias (o rival, {alvo:.0f})"
        else:
            for arquivo in (cand, cand.with_suffix(".json")):
                arquivo.unlink(missing_ok=True)
            cedo = f" já na luta {len(feitas)}" if faltam > 0 else ""
            texto = (f"🎯 Especialista novo de {nome} descartado{cedo}: {candidato}/{len(feitas)} "
                     f"(o rival, {alvo:.0f} em {self.LUTAS_AVALIACAO})")
        lutas["candidato"], lutas["rival"] = [], []
        a.pop("vez", None)
        a["desde_treino"] = 0
        return texto

    def precisa_treinar(self):
        """Uma arena com lutas novas suficientes e nenhum candidato em avaliação."""
        for cena, a in self.estado.items():
            if a["desde_treino"] >= self.LUTAS_PARA_TREINAR and not self.arquivo(cena, "candidato").exists():
                return cena
        return None

    def treinou(self, cena):
        """Treino desta arena terminou (com candidato novo ou sem novidade)."""
        a = self._da_arena(cena)
        a["desde_treino"] = 0
        a["lutas"]["candidato"], a["lutas"]["rival"] = [], []
        a["vez"] = "candidato"
        self.salvar()

    def guardar_dominado(self, cena, origem):
        """O cérebro que aprendeu a vencer este chefe: fica guardado para sempre em
        dominados/ e vira o especialista da arena (se ela ainda não tinha um).
        `origem`: o arquivo .npz do cérebro que jogava. Devolve o treino dele."""
        origem = Path(origem)
        info = origem.with_suffix(".json")
        treino = json.loads(info.read_text()).get("treino_id") if info.exists() else None
        destinos = [self.pasta / "dominados" / f"{cena}.npz"]
        if not self.arquivo(cena, "atual").exists():
            destinos.append(self.arquivo(cena, "atual"))
        for destino in destinos:
            destino.parent.mkdir(parents=True, exist_ok=True)
            if destino.resolve() != origem.resolve():
                shutil.copyfile(origem, destino)
            destino.with_suffix(".json").write_text(json.dumps({"treino_id": treino, "especialista": cena,
                                                                "dominado": True}))
        return treino

    def revisar(self):
        """Vereditos que já dá para dar (ex.: candidato que, pelas regras novas, já
        não alcança o rival). Devolve os avisos."""
        avisos = []
        for cena in list(self.estado):
            if self.arquivo(cena, "candidato").exists():
                veredito = self._veredito(cena)
                if veredito:
                    avisos.append(veredito)
        if avisos:
            self.salvar()
        return avisos

    def texto(self, cena, quem):
        if not quem:
            return ""
        nome = cena.removeprefix("GG_")
        lutas = self.estado.get(cena, {}).get("lutas", {})
        if self.arquivo(cena, "candidato").exists():
            feitas, rival = lutas.get("candidato", []), lutas.get("rival", [])
            vez = "candidato" if quem == "candidato" else "especialista atual"
            return (f"🎯 {nome}: vez do {vez} · candidato {sum(feitas)}/{len(feitas)} × "
                    f"rival {sum(rival)}/{len(rival)} (avaliando)")
        return f"🎯 especialista de {nome}"

    def salvar(self):
        self.pasta.mkdir(parents=True, exist_ok=True)
        temporario = self.arquivo_estado.with_suffix(".tmp")
        temporario.write_text(json.dumps(self.estado, ensure_ascii=False))
        temporario.replace(self.arquivo_estado)
