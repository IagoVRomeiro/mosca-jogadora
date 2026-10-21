"""Currículo de chefes no Salão dos Deuses: um chefe de cada vez, avançando por
domínio e revisando os já dominados.

- O chefe atual é o da primeira luta dela (a estátua que você escolheu) ou o de
  uma estátua que você escolher depois.
- Domínio: PARA_AVANCAR vitórias nas últimas JANELA lutas dele. Aí ela passa para
  a próxima estátua liberada, da esquerda para a direita (a ordem do Salão).
- Revisão: uma luta a cada REVISAO_A_CADA vai para um chefe já dominado, senão as
  partidas recentes dela que entram no treino seriam só do chefe atual.
- Empacou: EMPACOU_MIN sem dominar, o painel pede exemplos seus daquele chefe; com
  PULAR_MIN, ela passa para o próximo (o empacado fica marcado como pulado).

Panteões: cada estátua tem a sua sala (a mesma no panteão). Quando todos os
chefes de um panteão estiverem dominados nas estátuas, o painel avisa que ela
está pronta para ele (progresso_panteoes).

Só contam as lutas com a mosca no controle. O estado fica em curriculo.json.
"""

# Salas de um panteão que não são chefes (banco, passagens, fim)
SALAS_SEM_CHEFE = ("GG_Spa", "GG_Engine", "GG_End_Sequence", "GG_Unn", "GG_Atrium")

import json
import time
from pathlib import Path

from .config import PASTA


def nome_do_chefe(estatua):
    """GG_Statue_GruzMother -> GruzMother (o nome do objeto da estátua no jogo)."""
    return estatua.removeprefix("GG_Statue_") if estatua else "?"


class Curriculo:
    JANELA, PARA_AVANCAR = 10, 7
    REVISAO_A_CADA = 4
    EMPACOU_MIN, PULAR_MIN = 30, 60

    def __init__(self, arquivo=PASTA / "curriculo.json"):
        self.arquivo = Path(arquivo)
        self.estado = {"atual": None, "desde": None, "historico": {}, "dominados": [], "pulados": [],
                       "lutas": 0, "avisou": False, "salas": {}, "panteoes_prontos": []}
        if self.arquivo.exists():
            self.estado.update(json.loads(self.arquivo.read_text()))

    @property
    def atual(self):
        return self.estado["atual"]

    def _comecar(self, estatua, agora):
        self.estado.update(atual=estatua, desde=agora, avisou=False)

    def _seguinte(self, ordem):
        """A próxima estátua da ordem depois da atual que ainda não foi dominada."""
        feitas = set(self.estado["dominados"]) | set(self.estado["pulados"])
        depois = ordem[ordem.index(self.atual) + 1:] if self.atual in ordem else ordem
        for estatua in depois + ordem:
            if estatua not in feitas and estatua != self.atual:
                return estatua
        return None

    def registrar(self, estatua, venceu, ordem, agora=None, sala=""):
        """Uma luta dela terminou. Devolve avisos para o painel."""
        agora = time.time() if agora is None else agora
        e = self.estado
        avisos = []
        if not estatua:
            return avisos
        if sala:
            e.setdefault("salas", {})[estatua] = sala
        if self.atual is None or (estatua != self.atual and estatua not in e["dominados"]):
            self._comecar(estatua, agora)  # você escolheu outra estátua: ela vira a atual
        historico = e["historico"].setdefault(estatua, [])
        historico.append(1 if venceu else 0)
        del historico[:-self.JANELA]
        e["lutas"] += 1
        if estatua == self.atual:
            minutos = (agora - e["desde"]) / 60
            if len(historico) >= self.JANELA and sum(historico) >= self.PARA_AVANCAR:
                e["dominados"].append(estatua)
                seguinte = self._seguinte(ordem)
                avisos.append(f"🏆 Dominou {nome_do_chefe(estatua)} ({sum(historico)}/{len(historico)})"
                              + (f": agora {nome_do_chefe(seguinte)}" if seguinte else ": todos dominados!"))
                if seguinte:
                    self._comecar(seguinte, agora)
            elif minutos >= self.PULAR_MIN:
                e["pulados"].append(estatua)
                seguinte = self._seguinte(ordem)
                avisos.append(f"⏭ {nome_do_chefe(estatua)} sem domínio em {self.PULAR_MIN} min: "
                              + (f"passando para {nome_do_chefe(seguinte)}" if seguinte else "fica nele"))
                if seguinte:
                    self._comecar(seguinte, agora)
            elif minutos >= self.EMPACOU_MIN and not e["avisou"]:
                e["avisou"] = True
                avisos.append(f"🧩 Empacou em {nome_do_chefe(estatua)} ({sum(historico)}/{len(historico)}): "
                              "grave algumas lutas suas contra ele (Ctrl+Alt+G)")
        self.salvar()
        return avisos

    def progresso_panteoes(self, panteoes):
        """[(porta, chefes dominados, chefes)] de cada panteão liberado. Um chefe
        conta como dominado se a estátua dele (a da mesma sala) foi dominada."""
        dominadas = {self.estado.get("salas", {}).get(e) for e in self.estado["dominados"]}
        saida = []
        for p in panteoes:
            if not p.get("liberado"):
                continue
            chefes = [s for s in p.get("salas", []) if s and not s.startswith(SALAS_SEM_CHEFE)]
            if chefes:
                saida.append((p["porta"], sum(s in dominadas for s in chefes), len(chefes)))
        return saida

    def panteoes_novos_prontos(self, panteoes):
        """Avisos dos panteões que acabaram de ficar com todos os chefes dominados."""
        prontos = self.estado.setdefault("panteoes_prontos", [])
        avisos = []
        for porta, feitos, total in self.progresso_panteoes(panteoes):
            if feitos == total and porta not in prontos:
                prontos.append(porta)
                avisos.append(f"🏛 {porta}: os {total} chefes dominados nas estátuas. Leve-a até o panteão "
                              "(depois de cada tentativa ele recomeça sozinho)")
        if avisos:
            self.salvar()
        return avisos

    def proxima(self):
        """A estátua da próxima luta: a atual ou, a cada REVISAO_A_CADA, uma dominada."""
        e = self.estado
        if not self.atual:
            return ""
        if e["dominados"] and e["lutas"] % self.REVISAO_A_CADA == self.REVISAO_A_CADA - 1:
            return e["dominados"][(e["lutas"] // self.REVISAO_A_CADA) % len(e["dominados"])]
        return self.atual

    def texto(self):
        if not self.atual:
            return ""
        h = self.estado["historico"].get(self.atual, [])
        dominados = len(self.estado["dominados"])
        return (f"currículo: {nome_do_chefe(self.atual)} {sum(h)}/{len(h)}"
                + (f" · {dominados} dominado{'s' if dominados > 1 else ''}" if dominados else ""))

    def salvar(self):
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(self.estado, ensure_ascii=False))
        temporario.replace(self.arquivo)
