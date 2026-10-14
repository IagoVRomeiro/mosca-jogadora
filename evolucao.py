"""Evolução da mosca: um painel com a melhora versão a versão (dados do Supabase).

Uso:
    .venv-flygym/bin/python evolucao.py

Atualiza sozinho a cada minuto. Recompensa por minuto: maior é melhor; a barra
fina em cada versão é a incerteza (2 erros padrão entre as partidas).
"""

import mosca  # noqa: F401  (configura Qt antes de importar o resto)

import sys
import threading
import time
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from comparar import METRICAS, Versao, carregar, comparar_duas, texto_melhoria
from mosca.interface import COR_BORDA, COR_CARTAO, COR_TEXTO, COR_TEXTO_FRACO, ESTILO, cabecalho, rotulo
from registro import Supabase

# Cor = arquitetura (paleta categórica validada, passos do modo escuro)
COR_ARQUITETURA = {"mlp": "#3987e5", "conectoma": "#d95926"}  # azul, laranja
NOME_ARQUITETURA = {"mlp": "rede inventada", "conectoma": "conectoma"}
ATUALIZAR_S = 60
MINIMO_MINUTOS = 2


def cor(hexa, alfa=255):
    c = QtGui.QColor(hexa)
    c.setAlpha(alfa)
    return c


def grafico(titulo):
    """Gráfico com grade e eixos recessivos, no fundo do cartão."""
    g = pg.PlotWidget(background=COR_CARTAO)
    g.setTitle(titulo, color=COR_TEXTO, size="10pt")
    for eixo in ("left", "bottom"):
        a = g.getAxis(eixo)
        a.setPen(pg.mkPen(COR_BORDA))
        a.setTextPen(pg.mkPen(COR_TEXTO_FRACO))
    g.showGrid(x=False, y=True, alpha=0.12)
    g.setMenuEnabled(False)
    g.setMouseEnabled(False, False)
    g.hideButtons()
    return g


class Destaque(QtWidgets.QFrame):
    """Número de destaque com título e uma linha de contexto."""

    def __init__(self, titulo):
        super().__init__()
        self.setObjectName("metrica")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(rotulo(titulo, "fraco"))
        self.valor = rotulo("—", "valor")
        self.valor.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(self.valor)
        self.contexto = rotulo("", "fraco")
        self.contexto.setWordWrap(True)
        layout.addWidget(self.contexto)

    def definir(self, valor, contexto=""):
        self.valor.setText(valor)
        self.contexto.setText(contexto)


class PainelEvolucao(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("raiz")
        self.setWindowTitle("Evolução da mosca")
        self.resize(1400, 860)
        raiz = QtWidgets.QVBoxLayout(self)
        raiz.setContentsMargins(14, 14, 14, 14)
        raiz.setSpacing(12)

        cartao = QtWidgets.QFrame()
        cartao.setObjectName("cartao")
        layout = QtWidgets.QVBoxLayout(cartao)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        raiz.addWidget(cartao)

        caixa, linha, self.subtitulo = cabecalho("03", "Evolução da mosca", "carregando…")
        bt = QtWidgets.QPushButton("↻  Atualizar")
        bt.clicked.connect(lambda: self.atualizar())
        linha.addWidget(bt)
        layout.addLayout(caixa)

        # Destaques
        destaques = QtWidgets.QHBoxLayout()
        self.d_melhoria = Destaque("Melhoria desde a 1ª versão medida")
        self.d_campea = Destaque("Campeã atual")
        self.d_jogo = Destaque("A mosca já jogou")
        self.d_torneios = Destaque("Torneios")
        for d in (self.d_melhoria, self.d_campea, self.d_jogo, self.d_torneios):
            destaques.addWidget(d)
        layout.addLayout(destaques)

        # Gráficos principais
        meio = QtWidgets.QHBoxLayout()
        self.g_versoes = grafico("Recompensa por minuto de cada versão (maior é melhor)")
        self.g_tempo = grafico("Cada partida no tempo")
        self.g_tempo.setLabel("bottom", "minutos jogados pela mosca", color=COR_TEXTO_FRACO)
        meio.addWidget(self.g_versoes, stretch=3)
        meio.addWidget(self.g_tempo, stretch=2)
        layout.addLayout(meio, stretch=3)

        legenda = QtWidgets.QHBoxLayout()
        for arq, hexa in COR_ARQUITETURA.items():
            ponto = rotulo("■")
            ponto.setStyleSheet(f"color: {hexa}; font-size: 13px;")
            legenda.addWidget(ponto)
            legenda.addWidget(rotulo(NOME_ARQUITETURA[arq], "fraco"))
            legenda.addSpacing(12)
        legenda.addWidget(rotulo("🏆 campeã  ·  barra clara: menos de 2 min de jogo  ·  "
                                 "linha fina: incerteza (2 erros padrão)", "fraco"))
        legenda.addStretch()
        layout.addLayout(legenda)

        # Detalhe: medidas em escalas diferentes -> gráficos pequenos separados
        pequenos = QtWidgets.QHBoxLayout()
        self.g_detalhe = {}
        for campo, titulo in (("mortes", "Mortes/min (↓ melhor)"), ("danos", "Danos/min (↓ melhor)"),
                              ("acertos", "Acertos/min (↑ melhor)"), ("paradas", "Paradas/min (↓ melhor)")):
            g = grafico(titulo)
            self.g_detalhe[campo] = g
            pequenos.addWidget(g)
        layout.addLayout(pequenos, stretch=2)

        # Torneios
        layout.addWidget(rotulo("TORNEIOS", "secao"))
        self.tabela = QtWidgets.QTableWidget(0, 6)
        self.tabela.setHorizontalHeaderLabels(
            ["Desafiante", "Contra", "Resultado", "Desafiante /min", "Campeã /min", "Melhoria"])
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tabela.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.setMaximumHeight(150)
        self.tabela.setStyleSheet(
            f"QTableWidget {{ background: {COR_CARTAO}; gridline-color: {COR_BORDA}; border: none; }}"
            f"QHeaderView::section {{ background: #181c28; color: {COR_TEXTO_FRACO}; border: none; padding: 4px; }}")
        layout.addWidget(self.tabela)

        self._dados = None
        self._carregando = False
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._ver_se_chegou)
        self.timer.start(300)
        self.atualizar()
        self.relogio = QtCore.QTimer(self)
        self.relogio.timeout.connect(lambda: self.atualizar())
        self.relogio.start(ATUALIZAR_S * 1000)

    # --- dados (numa thread: a rede não trava a janela) ---

    def atualizar(self):
        if self._carregando:
            return
        self._carregando = True

        def buscar():
            try:
                banco = Supabase.do_env()
                treinos = {t["id"]: t for t in banco._pedir(
                    "GET", "/rest/v1/treinos?select=id,criado_em,config&order=id")}
                self._dados = (carregar(), treinos, None)
            except Exception as e:  # sem internet etc.: mostra o erro e tenta de novo depois
                self._dados = (None, None, str(e))
            self._carregando = False

        threading.Thread(target=buscar, daemon=True).start()

    def _ver_se_chegou(self):
        if self._dados is None:
            return
        versoes, treinos, erro = self._dados
        self._dados = None
        if erro:
            self.subtitulo.setText(f"⚠ não consegui ler o Supabase: {erro[:120]}")
            return
        self.desenhar(versoes, treinos)
        self.subtitulo.setText(f"dados do Supabase · atualizado às {time.strftime('%H:%M')} · "
                               f"atualiza sozinho a cada {ATUALIZAR_S} s")

    # --- desenho ---

    def desenhar(self, versoes, treinos):
        config = {tid: (t.get("config") or {}) for tid, t in treinos.items()}
        arquitetura = {tid: c.get("arquitetura", "mlp") for tid, c in config.items()}
        ids = sorted(t for t in versoes if t is not None)
        campea = self._campea()
        self._destaques(versoes, ids, campea, config)
        self._barras(versoes, ids, arquitetura, campea)
        self._linha_do_tempo(versoes)
        self._detalhes(versoes, ids, arquitetura)
        self._torneios(config)

    @staticmethod
    def _campea():
        import json

        from mosca.config import ARQUIVO_MODELO

        info = ARQUIVO_MODELO.with_suffix(".json")
        return json.loads(info.read_text()).get("treino_id") if info.exists() else None

    def _destaques(self, versoes, ids, campea, config):
        validas = [versoes[t] for t in ids if versoes[t].minutos >= MINIMO_MINUTOS]
        if len(validas) >= 2:
            _, _, pct, inc = comparar_duas(validas[0], validas[-1], "recompensa_total", True)
            self.d_melhoria.definir(
                "—" if pct is None else f"{pct:+.0f}%",
                f"do #{validas[0].treino_id} ao #{validas[-1].treino_id} · "
                + ("incerteza desconhecida" if inc is None else
                   f"±{inc:.0f}%" + (" (pode ser sorte)" if pct is not None and abs(pct) <= inc else "")))
        else:
            self.d_melhoria.definir("—", f"precisa de 2+ versões com {MINIMO_MINUTOS}+ min de jogo")
        if campea in versoes:
            v = versoes[campea]
            arq = NOME_ARQUITETURA.get(config.get(campea, {}).get("arquitetura", "mlp"))
            self.d_campea.definir(f"#{campea}", f"{arq} · {v.por_minuto('recompensa_total'):+.2f}/min "
                                                f"em {v.minutos:.1f} min")
        else:
            self.d_campea.definir(f"#{campea}" if campea else "—", "ainda sem partidas registradas")
        todas = [p for v in versoes.values() for p in v.partidas]
        minutos = sum(p["segundos"] for p in todas) / 60
        self.d_jogo.definir(f"{minutos:.0f} min", f"em {len(todas)} partidas")
        resultados = [c.get("torneio", {}).get("resultado") for c in config.values() if c.get("torneio")]
        self.d_torneios.definir(f"{resultados.count('venceu')} × {resultados.count('perdeu')}",
                                "vitórias × derrotas das desafiantes")

    def _barras(self, versoes, ids, arquitetura, campea):
        g = self.g_versoes
        g.clear()
        if not ids:
            return
        xs = np.arange(len(ids))
        valores = [versoes[t].por_minuto("recompensa_total") for t in ids]
        erros = [2 * versoes[t].erro_padrao("recompensa_total") for t in ids]
        pouco = [versoes[t].minutos < MINIMO_MINUTOS for t in ids]
        pinceis = [cor(COR_ARQUITETURA[arquitetura.get(t, "mlp")], 90 if p else 255) for t, p in zip(ids, pouco)]
        g.addItem(pg.BarGraphItem(x=xs, height=valores, width=0.6, brushes=pinceis,
                                  pen=pg.mkPen(COR_CARTAO, width=2)))
        finitos = [(x, v, e) for x, v, e in zip(xs, valores, erros) if np.isfinite(e)]
        if finitos:
            fx, fv, fe = (np.array(c) for c in zip(*finitos))
            g.addItem(pg.ErrorBarItem(x=fx, y=fv, top=fe, bottom=fe, beam=0.15,
                                      pen=pg.mkPen(COR_TEXTO_FRACO, width=1)))
        g.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(COR_BORDA, width=1)))
        # Dica ao passar o mouse: pontos invisíveis no topo de cada barra
        dicas = [f"#{t} · {NOME_ARQUITETURA[arquitetura.get(t, 'mlp')]}\n"
                 f"{v:+.2f} recompensa/min\n{versoes[t].minutos:.1f} min em {len(versoes[t].partidas)} partidas"
                 for t, v in zip(ids, valores)]
        g.addItem(pg.ScatterPlotItem(x=xs, y=valores, size=26, pen=None, brush=cor("#000000", 1),
                                     hoverable=True, tip=lambda x, y, data: data,
                                     data=dicas, hoverBrush=cor(COR_TEXTO, 40)))
        if campea in ids:
            i = ids.index(campea)
            topo = valores[i] + (erros[i] if np.isfinite(erros[i]) else 0)
            marca = pg.TextItem("🏆", anchor=(0.5, 1.2), color=COR_TEXTO)
            marca.setPos(i, max(topo, 0))
            g.addItem(marca)
        g.getAxis("bottom").setTicks([[(x, f"#{t}") for x, t in zip(xs, ids)]])

    def _linha_do_tempo(self, versoes):
        g = self.g_tempo
        g.clear()
        partidas = sorted((p for v in versoes.values() for p in v.partidas), key=lambda p: p["inicio"])
        if not partidas:
            return
        fim = np.cumsum([p["segundos"] / 60 for p in partidas])
        meio = fim - np.array([p["segundos"] / 120 for p in partidas])
        valores = np.array([p["recompensa_por_minuto"] for p in partidas])
        pesos = np.array([p["segundos"] for p in partidas])
        g.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(COR_BORDA, width=1)))
        dicas = [f"{datetime.fromisoformat(p['inicio']).astimezone():%d/%m %H:%M} · treino "
                 f"#{p['treino_id']}\n{p['recompensa_por_minuto']:+.2f}/min em {p['segundos'] / 60:.1f} min"
                 for p in partidas]
        g.addItem(pg.ScatterPlotItem(x=meio, y=valores, size=8, pen=pg.mkPen(COR_CARTAO, width=2),
                                     brush=cor(COR_TEXTO_FRACO, 200), hoverable=True,
                                     tip=lambda x, y, data: data, data=dicas))
        # Média móvel pesada pelo tempo (~10 min de jogo)
        media = [np.average(valores[max(0, i - 9) : i + 1], weights=pesos[max(0, i - 9) : i + 1])
                 for i in range(len(partidas))]
        g.plot(meio, media, pen=pg.mkPen("#3987e5", width=2))
        g.setTitle(f"Cada partida no tempo · média recente {media[-1]:+.1f}/min",
                   color=COR_TEXTO, size="10pt")

    def _detalhes(self, versoes, ids, arquitetura):
        validos = [t for t in ids if versoes[t].minutos >= MINIMO_MINUTOS]
        for campo, g in self.g_detalhe.items():
            g.clear()
            if not validos:
                continue
            xs = np.arange(len(validos))
            valores = [versoes[t].por_minuto(campo) for t in validos]
            pinceis = [cor(COR_ARQUITETURA[arquitetura.get(t, "mlp")]) for t in validos]
            g.addItem(pg.BarGraphItem(x=xs, height=valores, width=0.6, brushes=pinceis,
                                      pen=pg.mkPen(COR_CARTAO, width=2)))
            g.addItem(pg.ScatterPlotItem(
                x=xs, y=valores, size=22, pen=None, brush=cor("#000000", 1), hoverable=True,
                tip=lambda x, y, data: data, data=[f"#{t}: {v:.2f}/min" for t, v in zip(validos, valores)]))
            g.getAxis("bottom").setTicks([[(x, f"#{t}") for x, t in zip(xs, validos)]])

    def _torneios(self, config):
        linhas = [(tid, c["torneio"]) for tid, c in sorted(config.items(), reverse=True) if c.get("torneio")]
        self.tabela.setRowCount(len(linhas))
        for i, (tid, t) in enumerate(linhas):
            pct = t.get("melhoria_pct")
            celulas = [
                f"#{tid}", f"#{t.get('contra_treino')}",
                "🏆 venceu" if t.get("resultado") == "venceu" else "perdeu",
                f"{t.get('por_minuto', 0):+.2f}", f"{t.get('por_minuto_campea', 0):+.2f}",
                "—" if pct is None else f"{pct:+.0f}%",
            ]
            for j, texto in enumerate(celulas):
                item = QtWidgets.QTableWidgetItem(texto)
                item.setForeground(cor(COR_TEXTO))
                self.tabela.setItem(i, j, item)
        self.tabela.clearSpans()
        if not linhas:
            self.tabela.setRowCount(1)
            item = QtWidgets.QTableWidgetItem("nenhum torneio decidido ainda: deixe a mosca jogar com o 'Controlar jogo'")
            item.setForeground(cor(COR_TEXTO_FRACO))
            self.tabela.setItem(0, 0, item)
            self.tabela.setSpan(0, 0, 1, self.tabela.columnCount())


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(ESTILO)
    pg.setConfigOptions(antialias=True)
    if Supabase.do_env() is None:
        sys.exit("Supabase não configurado (.env).")
    janela = PainelEvolucao()
    janela.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
