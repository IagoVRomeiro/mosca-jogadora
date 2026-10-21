"""Evolução da mosca: um painel com a melhora versão a versão (dados do Supabase).

Uso:
    .venv-flygym/bin/python evolucao.py

Atualiza sozinho a cada minuto. Recompensa por minuto: maior é melhor; a barra
fina em cada versão é a incerteza (2 erros padrão entre as partidas).

Os gráficos de versão são das versões gerais (as que disputam o torneio). Os
especialistas de cada chefe e o currículo do Salão dos Deuses ficam nas tabelas
de baixo (lidos de curriculo.json e de especialistas/, que o painel da mosca
escreve).
"""

import mosca  # noqa: F401  (configura Qt antes de importar o resto)

import json
import sys
import threading
import time
from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from comparar import METRICAS, Versao, carregar, comparar_duas, texto_melhoria, todas
from mosca.curriculo import Curriculo, nome_do_chefe
from mosca.especialistas import PASTA_ESPECIALISTAS
from mosca.interface import COR_BORDA, COR_CARTAO, COR_TEXTO, COR_TEXTO_FRACO, ESTILO, cabecalho, rotulo
from registro import Supabase

# Cor = arquitetura (paleta categórica validada, passos do modo escuro)
COR_ARQUITETURA = {"mlp": "#3987e5", "conectoma": "#d95926"}  # azul, laranja
NOME_ARQUITETURA = {"mlp": "rede inventada", "conectoma": "conectoma"}
ATUALIZAR_S = 60
MINIMO_MINUTOS = 2
VERSOES_NO_GRAFICO = 30  # com todas (70+), as barras somem e os rótulos se sobrepõem


def cor(hexa, alfa=255):
    c = QtGui.QColor(hexa)
    c.setAlpha(alfa)
    return c


def rotulos(xs, ids, cada):
    """Rótulos do eixo das versões: um a cada `cada` (todos juntos se sobrepõem)."""
    return [[(x, f"#{t}") for i, (x, t) in enumerate(zip(xs, ids)) if i % cada == 0 or i == len(ids) - 1]]


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
        self.d_chefes = Destaque("Chefes dominados")
        for d in (self.d_melhoria, self.d_campea, self.d_jogo, self.d_torneios, self.d_chefes):
            destaques.addWidget(d)
        layout.addLayout(destaques)

        # Gráficos principais
        meio = QtWidgets.QHBoxLayout()
        self.g_versoes = grafico(f"Recompensa por minuto das últimas {VERSOES_NO_GRAFICO} versões (maior é melhor)")
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
        for campo, titulo in (("mortes", "Mortes/min (↓)"), ("danos", "Danos/min (↓)"),
                              ("acertos", "Acertos/min (↑)"), ("ajudas", "Ajudas/min (↓)"),
                              ("loops", "Loops/min (↓)"), ("salas_novas", "Salas novas/min (↑)")):
            g = grafico(titulo)
            self.g_detalhe[campo] = g
            pequenos.addWidget(g)
        layout.addLayout(pequenos, stretch=2)

        # Embaixo: torneios das versões gerais, currículo de chefes e especialistas
        baixo = QtWidgets.QHBoxLayout()
        self.tabela = self._tabela(["Desafiante", "Contra", "Resultado", "Ela /min", "Campeã /min", "Melhoria"])
        self.t_curriculo = self._tabela(["Chefe", "Últimas 10", "Situação"])
        self.t_especialistas = self._tabela(["Arena", "Treino", "Quem joga", "Vitórias (últimas 10)"])
        self.l_panteoes = rotulo("", "fraco")
        self.l_panteoes.setWordWrap(True)
        for titulo, tabela, extra, peso in (
            ("TORNEIOS (VERSÕES GERAIS)", self.tabela, None, 3),
            ("CURRÍCULO DE CHEFES", self.t_curriculo, self.l_panteoes, 2),
            ("ESPECIALISTAS POR CHEFE", self.t_especialistas, None, 3),
        ):
            coluna = QtWidgets.QVBoxLayout()
            coluna.addWidget(rotulo(titulo, "secao"))
            coluna.addWidget(tabela)
            if extra is not None:
                coluna.addWidget(extra)
            baixo.addLayout(coluna, stretch=peso)
        layout.addLayout(baixo)

        self._dados = None
        self._carregando = False
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._ver_se_chegou)
        self.timer.start(300)
        self.atualizar()
        self.relogio = QtCore.QTimer(self)
        self.relogio.timeout.connect(lambda: self.atualizar())
        self.relogio.start(ATUALIZAR_S * 1000)

    @staticmethod
    def _tabela(colunas):
        t = QtWidgets.QTableWidget(0, len(colunas))
        t.setHorizontalHeaderLabels(colunas)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        t.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setMaximumHeight(190)
        t.setStyleSheet(
            f"QTableWidget {{ background: {COR_CARTAO}; gridline-color: {COR_BORDA}; border: none; }}"
            f"QHeaderView::section {{ background: #181c28; color: {COR_TEXTO_FRACO}; border: none; padding: 4px; }}")
        return t

    @staticmethod
    def _preencher(tabela, linhas, vazio):
        tabela.clearSpans()
        tabela.setRowCount(max(1, len(linhas)))
        if not linhas:
            item = QtWidgets.QTableWidgetItem(vazio)
            item.setForeground(cor(COR_TEXTO_FRACO))
            tabela.setItem(0, 0, item)
            tabela.setSpan(0, 0, 1, tabela.columnCount())
            return
        for i, celulas in enumerate(linhas):
            for j, texto in enumerate(celulas):
                item = QtWidgets.QTableWidgetItem(texto)
                item.setForeground(cor(COR_TEXTO))
                tabela.setItem(i, j, item)

    # --- dados (numa thread: a rede não trava a janela) ---

    def atualizar(self):
        if self._carregando:
            return
        self._carregando = True

        def buscar():
            try:
                banco = Supabase.do_env()
                treinos = {t["id"]: t for t in todas(banco, "/rest/v1/treinos?select=id,criado_em,config&order=id")}
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
        # os especialistas jogam só na arena deles: não entram na comparação das gerais
        especialistas = {tid for tid, c in config.items() if c.get("especialista")}
        ids = sorted(t for t in versoes if t is not None and t not in especialistas)
        campea = self._campea()
        self._destaques(versoes, ids, campea, config)
        recentes = ids[-VERSOES_NO_GRAFICO:]
        self._barras(versoes, recentes, arquitetura, campea)
        self._linha_do_tempo(versoes)
        self._detalhes(versoes, recentes, arquitetura)
        self._torneios(config)
        self._curriculo()
        self._especialistas(config)

    def _curriculo(self):
        c = Curriculo()
        e = c.estado
        linhas = []
        for estatua, h in sorted(e.get("historico", {}).items(),
                                 key=lambda item: (item[0] != c.atual, item[0] not in e["dominados"], item[0])):
            situacao = ("🎯 atual" if estatua == c.atual else "✅ dominado" if estatua in e["dominados"]
                        else "⏭ pulado" if estatua in e.get("pulados", []) else "")
            linhas.append([nome_do_chefe(estatua), f"{sum(h)}/{len(h)}", situacao])
        self._preencher(self.t_curriculo, linhas,
                        "nenhuma luta ainda: escolha uma estátua no Salão dos Deuses e ligue a mosca")
        dominados = len(e.get("dominados", []))
        h = e.get("historico", {}).get(c.atual, [])
        self.d_chefes.definir(f"{dominados}", f"atual: {nome_do_chefe(c.atual)} ({sum(h)}/{len(h)})"
                              if c.atual else "currículo ainda não começou")
        progresso = c.progresso_panteoes(e.get("panteoes", []))
        self.l_panteoes.setText(
            "Panteões (chefes dominados nas estátuas): "
            + " · ".join(f"{porta.removeprefix('GG_')} {feitos}/{total}" for porta, feitos, total in progresso)
            if progresso else "Panteões: aparecem depois que ela passar pela sala das portas (GG_Atrium)")

    def _especialistas(self, config):
        estado = PASTA_ESPECIALISTAS / "estado.json"
        arenas = json.loads(estado.read_text()) if estado.exists() else {}
        linhas = []
        for arena, a in sorted(arenas.items()):
            info = {}
            for quem in ("candidato", "atual"):
                arquivo = PASTA_ESPECIALISTAS / (f"{arena}.candidato.json" if quem == "candidato" else f"{arena}.json")
                if arquivo.exists():
                    info[quem] = json.loads(arquivo.read_text()).get("treino_id")
            joga = "candidato" if "candidato" in info else "especialista" if "atual" in info else "versão geral"
            treino = " · ".join(f"#{tid}" + (" (cand.)" if quem == "candidato" else "")
                                for quem, tid in sorted(info.items()) if tid) or "—"
            lutas = a.get("lutas", {})
            vitorias = " · ".join(f"{nome} {sum(lutas[k])}/{len(lutas[k])}"
                                  for k, nome in (("atual", "esp."), ("candidato", "cand."), ("geral", "geral"))
                                  if lutas.get(k))
            linhas.append([arena.removeprefix("GG_"), treino, joga, vitorias or "—"])
        self._preencher(self.t_especialistas, linhas,
                        "nenhum ainda: o painel treina o de uma arena a cada 10 lutas dela ali")

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
        resultados = [c.get("torneio", {}).get("resultado") for c in config.values()
                      if c.get("torneio") and not c.get("especialista")]
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
        g.getAxis("bottom").setTicks(rotulos(xs, ids, 2))

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
            g.getAxis("bottom").setTicks(rotulos(xs, validos, 8))

    def _torneios(self, config):
        linhas = []
        for tid, c in sorted(config.items(), reverse=True):
            t = c.get("torneio")
            if not t or c.get("especialista"):
                continue
            pct = t.get("melhoria_pct")
            linhas.append([
                f"#{tid}", f"#{t.get('contra_treino')}",
                {"venceu": "🏆 venceu", "interrompida": "interrompida", "substituida": "substituída"}.get(
                    t.get("resultado"), "perdeu"),
                f"{t.get('por_minuto', 0):+.2f}", f"{t.get('por_minuto_campea', 0):+.2f}",
                "—" if pct is None else f"{pct:+.0f}%",
            ])
        self._preencher(self.tabela, linhas,
                        "nenhum torneio decidido ainda: deixe a mosca jogar com o 'Controlar jogo'")


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
