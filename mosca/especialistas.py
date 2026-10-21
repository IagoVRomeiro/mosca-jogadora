"""Especialistas por chefe: um cérebro para cada arena do Salão dos Deuses.

Um cérebro só (64 interneurônios na rede inventada) para mais de 40 chefes
aprende um e esquece parte do outro. Cada arena ganha uma versão própria, que
parte da campeã geral (ou do especialista anterior) e é afinada só com as lutas
daquela arena, suas e dela (treinar.py --especialista CENA).

- Treino: a cada LUTAS_PARA_TREINAR lutas da arena sem candidato pendente.
- Avaliação: o candidato joga as próximas LUTAS_AVALIACAO lutas da arena. Assume
  se vencer pelo menos tanto quanto quem jogava antes (o especialista atual, ou a
  versão geral nas últimas lutas dela ali); senão, é descartado.
- No jogo: dentro da arena joga o especialista (o candidato, enquanto é avaliado);
  fora dela, a campeã ou a desafiante geral, como sempre.

Arquivos em especialistas/: <cena>.npz (o atual) e <cena>.candidato.npz, cada um
com o .json do treino. O estado (lutas de cada um) fica em especialistas/estado.json.
"""

import json
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
        """'candidato' (em avaliação), 'atual' ou None (sem especialista: a geral)."""
        for quem in ("candidato", "atual"):
            if self.arquivo(cena, quem).exists():
                return quem
        return None

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
        lutas.setdefault(quem, []).append(1 if venceu else 0)
        for k in lutas:
            del lutas[k][:-max(self.LUTAS_AVALIACAO, self.LUTAS_PARA_TREINAR)]
        a["desde_treino"] += 1
        avisos = []
        if quem == "candidato" and len(lutas["candidato"]) >= self.LUTAS_AVALIACAO:
            avisos.append(self._veredito(cena))
        self.salvar()
        return avisos

    def _veredito(self, cena):
        a = self.estado[cena]
        lutas = a["lutas"]
        candidato = sum(lutas["candidato"][-self.LUTAS_AVALIACAO:])
        referencia = lutas["atual"] if self.arquivo(cena, "atual").exists() else lutas["geral"]
        antes = referencia[-self.LUTAS_AVALIACAO:]
        # proporção: a referência pode ter menos lutas guardadas
        alvo = sum(antes) / len(antes) * self.LUTAS_AVALIACAO if antes else 0
        cand = self.arquivo(cena, "candidato")
        nome = cena.removeprefix("GG_")
        if candidato >= alvo:
            atual = self.arquivo(cena, "atual")
            for origem, destino in ((cand, atual), (cand.with_suffix(".json"), atual.with_suffix(".json"))):
                if origem.exists():
                    origem.replace(destino)
            lutas["atual"] = list(lutas["candidato"])
            texto = f"🎯 Especialista de {nome} assumiu: {candidato}/{self.LUTAS_AVALIACAO} vitórias (antes {alvo:.0f})"
        else:
            for arquivo in (cand, cand.with_suffix(".json")):
                arquivo.unlink(missing_ok=True)
            texto = f"🎯 Especialista novo de {nome} descartado: {candidato}/{self.LUTAS_AVALIACAO} (antes {alvo:.0f})"
        lutas["candidato"] = []
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
        a["lutas"]["candidato"] = []
        self.salvar()

    def texto(self, cena, quem):
        if not quem:
            return ""
        nome = cena.removeprefix("GG_")
        if quem == "candidato":
            feitas = self.estado.get(cena, {}).get("lutas", {}).get("candidato", [])
            return f"🎯 candidato de {nome} {sum(feitas)}/{len(feitas)} (avaliando {self.LUTAS_AVALIACAO})"
        return f"🎯 especialista de {nome}"

    def salvar(self):
        self.pasta.mkdir(parents=True, exist_ok=True)
        temporario = self.arquivo_estado.with_suffix(".tmp")
        temporario.write_text(json.dumps(self.estado, ensure_ascii=False))
        temporario.replace(self.arquivo_estado)
