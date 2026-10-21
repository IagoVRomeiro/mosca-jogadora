"""Chefes: as estatísticas de cada chefe do Salão dos Deuses, suas e da mosca.

Uso:
    .venv-flygym/bin/python chefes.py      (ou o botão "📊 Chefes" do painel)

À esquerda, todos os chefes já enfrentados; clicando num, à direita: quanto da
vida dele ela tirou em cada luta, a taxa de vitória ao longo das lutas, o dano
que ela tomou e a comparação com você. As lutas vêm das gravações
(mosca/estatisticas.py) e ficam guardadas mesmo depois que a gravação é apagada.
No topo e na tabela também ficam o currículo do Salão dos Deuses (dominados,
pulados, panteões) e os especialistas de cada arena (curriculo.json e
especialistas/, que o painel da mosca escreve). Atualiza sozinho a cada minuto.
"""

import mosca  # noqa: F401  (configura Qt antes de importar o resto)

import json
import sys
import threading
import time
from collections import defaultdict

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

from evolucao import Destaque, cor, grafico
from mosca.curriculo import Curriculo, nome_do_chefe
from mosca.especialistas import PASTA_ESPECIALISTAS
from mosca.estatisticas import carregar, nome_da_luta, resumo
from mosca.interface import COR_BORDA, COR_CARTAO, COR_TEXTO, COR_TEXTO_FRACO, ESTILO, cabecalho, rotulo

ATUALIZAR_S = 60
COR_VITORIA, COR_DERROTA = "#2fb36b", "#d95926"  # verde, laranja
COR_ELA, COR_VOCE = "#3987e5", "#b0b8cc"  # azul (ela), cinza claro (você)
JANELA = 10  # lutas da média móvel


def tabela(colunas):
    t = QtWidgets.QTableWidget(0, len(colunas))
    t.setHorizontalHeaderLabels(colunas)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
    t.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    t.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
    t.setStyleSheet(
        f"QTableWidget {{ background: {COR_CARTAO}; gridline-color: {COR_BORDA}; border: none; }}"
        f"QTableWidget::item:selected {{ background: #2a3350; }}"
        f"QHeaderView::section {{ background: #181c28; color: {COR_TEXTO_FRACO}; border: none; padding: 4px; }}")
    return t


def nome(sala):
    """Nome para mostrar: a sala da luta, ou a estátua quando ainda não se sabe a sala dela."""
    return nome_do_chefe(sala) + " (estátua)" if sala.startswith("GG_Statue_") else nome_da_luta(sala)


def media_movel(valores, n=JANELA):
    v = np.asarray(valores, float)
    return np.array([v[max(0, i - n + 1): i + 1].mean() for i in range(len(v))])


class PainelChefes(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("raiz")
        self.setWindowTitle("Chefes da mosca")
        self.resize(1500, 900)
        raiz = QtWidgets.QVBoxLayout(self)
        raiz.setContentsMargins(14, 14, 14, 14)
        cartao = QtWidgets.QFrame()
        cartao.setObjectName("cartao")
        layout = QtWidgets.QVBoxLayout(cartao)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        raiz.addWidget(cartao)

        caixa, linha, self.subtitulo = cabecalho("04", "Chefes", "carregando…")
        bt = QtWidgets.QPushButton("↻  Atualizar")
        bt.clicked.connect(lambda: self.atualizar())
        linha.addWidget(bt)
        layout.addLayout(caixa)

        # Topo: o currículo do Salão dos Deuses
        resumo_topo = QtWidgets.QHBoxLayout()
        self.d_dominados = Destaque("Chefes dominados")
        self.d_atual = Destaque("Chefe atual do currículo")
        self.d_pulados = Destaque("Pulados")
        self.d_especialistas = Destaque("Especialistas")
        for d in (self.d_dominados, self.d_atual, self.d_pulados, self.d_especialistas):
            resumo_topo.addWidget(d)
        layout.addLayout(resumo_topo)
        self.l_panteoes = rotulo("", "fraco")
        self.l_panteoes.setWordWrap(True)
        layout.addWidget(self.l_panteoes)

        corpo = QtWidgets.QHBoxLayout()
        layout.addLayout(corpo, stretch=1)

        # Esquerda: todos os chefes
        esquerda = QtWidgets.QVBoxLayout()
        esquerda.addWidget(rotulo("CHEFES · lutas, vitórias e melhor luta são dela (clique para ver)", "secao"))
        self.t_chefes = tabela(["Chefe", "Currículo", "Lutas", "Vitórias", "Últ. 10", "Melhor", "Suas lutas",
                                "Especialista", "Esp. × geral (últ. 10)"])
        self.t_chefes.itemSelectionChanged.connect(self._escolheu)
        esquerda.addWidget(self.t_chefes)
        self.l_rodape = rotulo("", "fraco")
        self.l_rodape.setWordWrap(True)
        esquerda.addWidget(self.l_rodape)
        corpo.addLayout(esquerda, stretch=5)

        # Direita: o chefe escolhido
        direita = QtWidgets.QVBoxLayout()
        self.l_chefe = rotulo("", "valor")
        self.l_chefe.setStyleSheet("font-size: 20px; font-weight: 600;")
        direita.addWidget(self.l_chefe)
        destaques = QtWidgets.QHBoxLayout()
        self.d_vitorias = Destaque("Vitórias dela")
        self.d_recente = Destaque(f"Últimas {JANELA}")
        self.d_melhor = Destaque("Melhor luta")
        self.d_voce = Destaque("Seus exemplos")
        for d in (self.d_vitorias, self.d_recente, self.d_melhor, self.d_voce):
            destaques.addWidget(d)
        direita.addLayout(destaques)
        grade = QtWidgets.QGridLayout()
        self.g_chefe = grafico("% do chefe tirado por luta (verde venceu, laranja perdeu)")
        self.g_taxa = grafico(f"Vitórias nas últimas {JANELA} lutas (%)")
        self.g_dano = grafico("Dano tomado por minuto em cada luta (↓)")
        self.g_comparar = grafico("Você × ela, por minuto de luta")
        for g in (self.g_chefe, self.g_taxa, self.g_dano):
            g.setLabel("bottom", "lutas dela, da primeira à última", color=COR_TEXTO_FRACO)
        grade.addWidget(self.g_chefe, 0, 0)
        grade.addWidget(self.g_taxa, 0, 1)
        grade.addWidget(self.g_dano, 1, 0)
        grade.addWidget(self.g_comparar, 1, 1)
        direita.addLayout(grade, stretch=1)
        corpo.addLayout(direita, stretch=7)

        self._por_sala, self._salas, self._dados, self._carregando = {}, [], None, False
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._ver_se_chegou)
        self.timer.start(300)
        self.atualizar()
        self.relogio = QtCore.QTimer(self)
        self.relogio.timeout.connect(lambda: self.atualizar())
        self.relogio.start(ATUALIZAR_S * 1000)

    # --- dados (numa thread: ler as gravações não trava a janela) ---

    def atualizar(self):
        if self._carregando:
            return
        self._carregando = True

        def buscar():
            try:
                self._dados = (carregar(), None)
            except Exception as e:
                self._dados = (None, str(e))
            self._carregando = False

        threading.Thread(target=buscar, daemon=True).start()

    def _ver_se_chegou(self):
        if self._dados is None:
            return
        lutas, erro = self._dados
        self._dados = None
        if erro:
            self.subtitulo.setText(f"⚠ não consegui ler as gravações: {erro[:120]}")
            return
        self.desenhar(lutas)
        self.subtitulo.setText(f"{len(lutas)} lutas nas gravações · atualizado às {time.strftime('%H:%M')} · "
                               f"atualiza sozinho a cada {ATUALIZAR_S} s")

    # --- desenho ---

    @staticmethod
    def _especialistas():
        """{arena: (quem joga lá, vitórias nas últimas 10 de cada um)}."""
        estado = PASTA_ESPECIALISTAS / "estado.json"
        arenas = json.loads(estado.read_text()) if estado.exists() else {}
        saida = {}
        for arena, a in arenas.items():
            joga = "versão geral"
            for sufixo, quem in ((".candidato.json", "candidato"), (".json", "especialista")):
                info = PASTA_ESPECIALISTAS / f"{arena}{sufixo}"
                if info.exists():
                    tid = json.loads(info.read_text()).get("treino_id")
                    joga = f"#{tid}" + (" (aval.)" if quem == "candidato" else "")
                    break
            lutas = a.get("lutas", {})
            vitorias = " · ".join(f"{sigla} {sum(lutas[k])}/{len(lutas[k])}"
                                  for k, sigla in (("atual", "esp."), ("candidato", "cand."), ("geral", "geral"))
                                  if lutas.get(k))
            saida[arena] = (joga, vitorias or "—")
        return saida

    def _curriculo(self, especialistas):
        """Destaques e panteões do topo; devolve {sala: situação no currículo} para a tabela."""
        c = Curriculo()
        e = c.estado
        sala_de = e.get("salas", {})
        situacoes = {}
        for estatua, h in e.get("historico", {}).items():
            marca = ("🎯 atual" if estatua == c.atual else "✅ dominado" if estatua in e["dominados"]
                     else "⏭ pulado" if estatua in e.get("pulados", []) else "")
            situacoes[sala_de.get(estatua, estatua)] = f"{marca} · {sum(h)}/{len(h)}" if marca else f"{sum(h)}/{len(h)}"
        h = e.get("historico", {}).get(c.atual, [])
        self.d_dominados.definir(f"{len(e.get('dominados', []))}", "7 vitórias nas últimas 10 domina um chefe")
        self.d_atual.definir(nome_do_chefe(c.atual) if c.atual else "—",
                             f"{sum(h)}/{len(h)} nas últimas lutas" if c.atual else "currículo ainda não começou")
        pulados = [p for p in e.get("pulados", []) if p not in e.get("dominados", [])]
        self.d_pulados.definir(f"{len(pulados)}", ", ".join(nome_do_chefe(p) for p in pulados) or "nenhum")
        proprios = [a for a, (joga, _) in especialistas.items() if joga != "versão geral"]
        self.d_especialistas.definir(f"{len(proprios)}", f"de {len(especialistas)} arenas com lutas registradas"
                                     if especialistas else "o painel treina o de uma arena a cada 10 lutas dela ali")
        progresso = c.progresso_panteoes(e.get("panteoes", []))
        self.l_panteoes.setText(
            "Panteões (chefes dominados nas estátuas): "
            + " · ".join(f"{porta.removeprefix('GG_')} {feitos}/{total}" for porta, feitos, total in progresso)
            if progresso else "Panteões: aparecem depois que ela passar pela sala das portas (GG_Atrium)")
        return situacoes

    def desenhar(self, lutas):
        por_sala = defaultdict(lambda: {"mosca": [], "voce": []})
        for luta in lutas:
            if luta["quem"] in ("mosca", "voce"):
                por_sala[luta["sala"]][luta["quem"]].append(luta)
        especialistas = self._especialistas()
        situacoes = self._curriculo(especialistas)
        for sala in [*situacoes, *especialistas]:
            por_sala[sala]  # chefes do currículo e arenas sem luta nas gravações também aparecem
        c = Curriculo()
        atual = c.estado.get("salas", {}).get(c.atual, c.atual)
        # ordem: as dela com mais lutas primeiro, depois as só suas
        salas = sorted(por_sala, key=lambda s: (-len(por_sala[s]["mosca"]), -len(por_sala[s]["voce"]), s))
        escolhida = self._sala_escolhida()
        self._por_sala, self._salas = por_sala, salas
        self.t_chefes.blockSignals(True)
        self.t_chefes.setRowCount(len(salas))
        for i, sala in enumerate(salas):
            ela, voce = resumo(por_sala[sala]["mosca"]), resumo(por_sala[sala]["voce"])
            completas = [x for x in por_sala[sala]["mosca"] if x["completa"]]
            recentes = completas[-JANELA:]
            joga, vitorias_esp = especialistas.get(sala, ("—", "—"))
            celulas = [
                ("🎯 " if sala == atual else "") + nome(sala),
                situacoes.get(sala, "—"),
                f"{ela['lutas']}" if ela else "—",
                f"{ela['vitorias']} ({ela['vitorias'] / ela['lutas']:.0%})" if ela else "—",
                f"{sum(x['venceu'] for x in recentes)}/{len(recentes)}" if recentes else "—",
                f"{ela['melhor_chefe']}%" if ela else "—",
                f"{voce['lutas']}" if voce else "—",
                joga,
                vitorias_esp,
            ]
            for j, texto in enumerate(celulas):
                item = QtWidgets.QTableWidgetItem(texto)
                item.setForeground(cor(COR_TEXTO if ela or j == 0 else COR_TEXTO_FRACO))
                self.t_chefes.setItem(i, j, item)
        self.t_chefes.blockSignals(False)
        self.l_rodape.setText(
            "🎯 = chefe atual do currículo. Currículo: situação e vitórias nas últimas 10 lutas dela na estátua "
            "(7/10 domina). Esp. × geral: vitórias do especialista, do candidato e da versão geral naquela arena. "
            "Lutas cortadas pelo começo ou fim de uma gravação não contam. "
            "Salas \"V\" (ex.: Gruz Mother V) são outras versões da luta, com especialista próprio.")
        if salas:
            linha = salas.index(escolhida) if escolhida in salas else 0
            self.t_chefes.selectRow(linha)
            self._mostrar(salas[linha])

    def _sala_escolhida(self):
        linhas = self.t_chefes.selectionModel().selectedRows() if self.t_chefes.selectionModel() else []
        return self._salas[linhas[0].row()] if linhas and linhas[0].row() < len(self._salas) else None

    def _escolheu(self):
        sala = self._sala_escolhida()
        if sala:
            self._mostrar(sala)

    def _mostrar(self, sala):
        dados = self._por_sala[sala]
        ela = [x for x in dados["mosca"] if x["completa"]]
        voce = [x for x in dados["voce"] if x["completa"]]
        r_ela, r_voce = resumo(ela), resumo(voce)
        self.l_chefe.setText(nome(sala))
        if r_ela:
            self.d_vitorias.definir(f"{r_ela['vitorias']}/{r_ela['lutas']}",
                                    f"{r_ela['vitorias'] / r_ela['lutas']:.0%} · {r_ela['segundos_por_luta']:.0f} s por luta")
            recentes = ela[-JANELA:]
            self.d_recente.definir(f"{sum(x['venceu'] for x in recentes)}/{len(recentes)}",
                                   "domínio no currículo: 7/10")
            self.d_melhor.definir(f"{r_ela['melhor_chefe']}%", "da vida do chefe numa luta só")
        else:
            for d in (self.d_vitorias, self.d_recente, self.d_melhor):
                d.definir("—", "ela ainda não lutou aqui")
        self.d_voce.definir(f"{r_voce['lutas']} lutas" if r_voce else "nenhuma",
                            f"{r_voce['minutos']:.1f} min · você venceu {r_voce['vitorias']}" if r_voce
                            else "grave algumas (Ctrl+Alt+G): é o que mais ensina")
        self._desenhar_lutas(ela)
        self._desenhar_comparacao(r_ela, r_voce)

    def _desenhar_lutas(self, ela):
        for g in (self.g_chefe, self.g_taxa, self.g_dano):
            g.clear()
        if not ela:
            return
        xs = np.arange(1, len(ela) + 1)
        chefe = np.array([min(x["dano_chefe"], 100) for x in ela])
        venceu = np.array([x["venceu"] for x in ela])
        dicas = [f"luta {i} · {x['inicio'][5:16].replace('T', ' ')}\n{'venceu' if x['venceu'] else 'perdeu'} · "
                 f"{min(x['dano_chefe'], 100)}% do chefe · {x['segundos']:.0f} s · {x['dano']} danos"
                 for i, x in zip(xs, ela)]
        pinceis = [cor(COR_VITORIA if v else COR_DERROTA) for v in venceu]
        self.g_chefe.addItem(pg.ScatterPlotItem(x=xs, y=chefe, size=7, pen=pg.mkPen(COR_CARTAO, width=1),
                                                brush=pinceis, hoverable=True, data=dicas,
                                                tip=lambda x, y, data: data))
        self.g_chefe.plot(xs, media_movel(chefe), pen=pg.mkPen(COR_ELA, width=2))
        self.g_chefe.setYRange(0, 105)
        self.g_taxa.plot(xs, 100 * media_movel(venceu), pen=pg.mkPen(COR_VITORIA, width=2))
        self.g_taxa.addItem(pg.InfiniteLine(pos=70, angle=0, pen=pg.mkPen(COR_TEXTO_FRACO, width=1,
                                                                          style=QtCore.Qt.PenStyle.DashLine)))
        self.g_taxa.setYRange(0, 105)
        dano = np.array([x["dano"] / max(x["segundos"], 1) * 60 for x in ela])
        self.g_dano.addItem(pg.ScatterPlotItem(x=xs, y=dano, size=6, pen=None, brush=cor(COR_TEXTO_FRACO, 160)))
        self.g_dano.plot(xs, media_movel(dano), pen=pg.mkPen(COR_DERROTA, width=2))

    def _desenhar_comparacao(self, ela, voce):
        g = self.g_comparar
        g.clear()
        medidas = [("acerto", "golpes"), ("dano", "dano tomado"), ("cura", "curas"), ("magia", "magias")]
        xs = np.arange(len(medidas))
        for deslocamento, r, hexa in ((-0.18, voce, COR_VOCE), (0.18, ela, COR_ELA)):
            if r is None:
                continue
            valores = [r[m] for m, _ in medidas]
            g.addItem(pg.BarGraphItem(x=xs + deslocamento, height=valores, width=0.34, brush=cor(hexa),
                                      pen=pg.mkPen(COR_CARTAO, width=1)))
        g.getAxis("bottom").setTicks([[(x, nome) for x, (_, nome) in zip(xs, medidas)]])
        g.setXRange(-0.6, len(medidas) - 0.4, padding=0)
        g.setTitle("Você (cinza) × ela (azul), por minuto de luta", color=COR_TEXTO, size="10pt")


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(ESTILO)
    pg.setConfigOptions(antialias=True)
    janela = PainelChefes()
    janela.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
