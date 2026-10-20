"""De onde vem o jogo: o jogo de demonstração e a captura da janela do Hollow Knight
(que também manda as teclas da mosca para ele)."""

import socket
import time

import numpy as np

from .config import (
    ACOES, ACOES_JOGO, DURACAO_TOQUE_S, OPOSTAS, SEGURAR_MAXIMO_S, SEGURAR_MINIMO_S, SOLTO_S, TOQUE_S,
)


class JogoDemo:
    """Plataforma 2D simples no lugar do Hollow Knight, para testar o fluxo."""

    def __init__(self, w=480, h=270):
        self.w, self.h = w, h
        self.chao = h - 40
        self.reiniciar()

    def reiniciar(self):
        self.x, self.y, self.vy = self.w / 2, self.chao, 0.0
        self.inimigos = [[60.0, 1.5], [self.w - 60.0, -2.0]]
        self.ataque = 0

    def passo(self, acoes):
        direcao = acoes["Direita"] - acoes["Esquerda"]
        vx = 6 * direcao + (8 * np.sign(direcao) if acoes["Esquiva"] > 0.5 else 0)
        self.x = float(np.clip(self.x + vx, 10, self.w - 10))
        if acoes["Pular"] > 0.5 and self.y >= self.chao:
            self.vy = -9
        self.vy += 0.6
        self.y = min(self.y + self.vy, self.chao)
        self.ataque = 6 if acoes["Atacar"] > 0.5 else max(self.ataque - 1, 0)
        for ini in self.inimigos:
            ini[0] += ini[1]
            if not 10 < ini[0] < self.w - 10:
                ini[1] *= -1

    def quadro(self):
        img = np.zeros((self.h, self.w, 3), dtype=np.uint8)
        img[:] = (18, 22, 40)
        img[self.chao + 12 :] = (60, 60, 70)
        yy, xx = np.mgrid[0 : self.h, 0 : self.w]
        for ix, _ in self.inimigos:
            m = ((xx - ix) / 14) ** 2 + ((yy - self.chao) / 10) ** 2 < 1
            img[m] = (230, 120, 40)
        x, y = int(self.x), int(self.y)
        img[max(y - 22, 0) : y + 12, x - 7 : x + 7] = (235, 235, 245)
        if self.ataque:
            img[max(y - 10, 0) : y - 4, x + 7 : x + 32] = (250, 250, 180)
        return img


class CapturaJanela:
    """Captura uma janela X11 pelo nome exato (ex.: o Hollow Knight no Proton).

    Lê direto da janela, então funciona mesmo com outras janelas por cima. Só não
    funciona com ela minimizada: aí o jogo não desenha nada. As teclas pelo XTest
    só chegam com o jogo em foco (ver `_foco`); com o plugin aceitando teclas
    (`pelo_plugin`), elas vão por dentro do jogo e o foco não importa.
    """

    PORTA_PLUGIN = 47124  # mod/MoscaEventos: ações que a mosca está segurando
    pelo_plugin = False  # ligado pelo painel quando o plugin diz que aceita teclas
    _sock_plugin = None

    # Teclas padrão do Hollow Knight
    TECLAS = {nome: a.tecla for nome, a in ACOES_JOGO.items()}
    APERTAR, SOLTAR = 0.5, 0.35  # histerese para a tecla não ficar piscando

    def __init__(self, nome="Hollow Knight"):
        from Xlib import X, XK, display
        from Xlib.ext import xtest
        from Xlib.protocol import event

        self._X, self._evento, self._xtest = X, event, xtest
        self.nome = nome
        self.display = display.Display()
        self._wm_state = self.display.intern_atom("WM_STATE")
        self._janela_ativa = self.display.intern_atom("_NET_ACTIVE_WINDOW")
        self._codigos = {
            acao: self.display.keysym_to_keycode(XK.string_to_keysym(tecla))
            for acao, tecla in self.TECLAS.items()
        }
        self._codigo_esc = self.display.keysym_to_keycode(XK.string_to_keysym("Escape"))
        self.janela = None
        self.aviso = None
        self.controlando = False  # só manda teclas quando ligado no painel
        self.apertadas = set()  # teclas fisicamente apertadas agora
        self._ativas = set()  # ações que a mosca quer (podem estar entre dois toques)
        self._desde, self._apertou_em = {}, {}
        self._soltou_em = {}  # quando a mosca soltou cada tecla (ver da_mosca)
        self._fisicas = set()  # códigos de tecla apertados de verdade (Foco e Magia dividem o K)
        self._solto_ate = {}  # tecla solta por um instante (SEGURAR_MAXIMO_S): até quando
        self.janelas_proprias = set()  # o painel: pode devolver o foco ao jogo
        self.aviso_controle = None
        self._ultimo_foco = 0.0
        self._vazio = np.zeros((360, 640, 3), dtype=np.uint8)

    def reiniciar(self):
        self.soltar_tudo()

    # O jogo (Wine/Unity) ignora teclas enquanto não está em foco, então as teclas
    # são simuladas com XTEST, como um teclado de verdade. Como o XTEST digita na
    # janela em foco, só apertamos com o foco no jogo: nunca no VS Code etc.

    def _foco(self):
        prop = self.display.screen().root.get_full_property(self._janela_ativa, self._X.AnyPropertyType)
        return prop.value[0] if prop is not None and len(prop.value) else None

    def em_foco(self):
        return self.janela is not None and self._foco() == self.janela.id

    def recebe_teclas(self):
        """As teclas da mosca chegam ao jogo: pelo plugin, ou pelo XTest com foco."""
        return self.janela is not None and (self.pelo_plugin or self.em_foco())

    def _mandar_ao_plugin(self, acoes):
        """As ações que a mosca segura agora. O plugin solta tudo se elas pararem de
        chegar, então vai a cada quadro, mesmo sem mudança."""
        if self._sock_plugin is None:
            self._sock_plugin = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # "1|" com a mosca no controle: o plugin só a leva de volta à luta assim
        pacote = f"{1 if self.controlando else 0}|" + ",".join(sorted(acoes))
        try:
            self._sock_plugin.sendto(pacote.encode(), ("127.0.0.1", self.PORTA_PLUGIN))
        except OSError:
            pass

    def teclas_do_usuario(self):
        """Teclas de ação que estão apertadas agora (na ordem de ACOES). Uma tecla
        de duas ações (K: Foco e Magia) conta só na primeira; o treino separa
        toque (Magia) de segurado (Foco) pela duração."""
        mapa = self.display.query_keymap()
        vistos, saida = set(), []
        for a in ACOES:
            c = self._codigos[a]
            saida.append(bool(mapa[c // 8] & (1 << (c % 8))) and c not in vistos)
            vistos.add(c)
        return np.array(saida)

    def esc_apertado(self):
        """Esc apertado agora, em qualquer janela (a mosca nunca aperta Esc)."""
        codigo = getattr(self, "_codigo_esc", None)
        if not codigo:
            return False
        mapa = self.display.query_keymap()
        return bool(mapa[codigo // 8] & (1 << (codigo % 8)))

    def da_mosca(self, folga=0.25):
        """Teclas da mosca: as apertadas e as soltas há menos de `folga` s (o jogo
        e o plugin ainda podem vê-las acionadas por um instante)."""
        agora = time.monotonic()
        mosca = set(self.apertadas) | {a for a, t in self._soltou_em.items() if agora - t < folga}
        # o jogo vê a tecla, não a ação: a Magia da mosca aparece como Foco
        codigos = {self._codigos[a] for a in mosca}
        return mosca | {a for a in self.TECLAS if self._codigos[a] in codigos}

    def focar(self):
        """Pede ao gerenciador de janelas para trazer o jogo para o foco."""
        if self.janela is None or time.monotonic() - self._ultimo_foco < 0.5:
            return
        self._ultimo_foco = time.monotonic()
        root = self.display.screen().root
        ev = self._evento.ClientMessage(
            window=self.janela, client_type=self._janela_ativa,
            data=(32, [2, self._X.CurrentTime, 0, 0, 0]),  # 2 = pedido vindo de "ferramenta"
        )
        mascara = self._X.SubstructureRedirectMask | self._X.SubstructureNotifyMask
        root.send_event(ev, event_mask=mascara)
        self.display.flush()

    def _tecla(self, acao, apertar):
        """Aperta ou solta de verdade a tecla de `acao`."""
        tipo = self._X.KeyPress if apertar else self._X.KeyRelease
        self._xtest.fake_input(self.display, tipo, self._codigos[acao])

    def _sincronizar(self):
        """Teclas físicas = as das ações apertadas. Duas ações na mesma tecla (K)
        não brigam: ela fica apertada se qualquer uma quiser. Pelo plugin, nenhuma
        tecla física: as ações vão direto para ele."""
        # sempre manda (vazio pelo XTest): o plugin conta o que lê, e é assim que o
        # painel sabe que pode passar as teclas por ele
        self._mandar_ao_plugin(self.apertadas if self.pelo_plugin else ())
        querem = {}
        for acao in () if self.pelo_plugin else self.apertadas:
            querem.setdefault(self._codigos[acao], acao)
        for codigo, acao in querem.items():
            if codigo not in self._fisicas:
                self._tecla(acao, True)
                self._fisicas.add(codigo)
        for codigo in list(self._fisicas - set(querem)):
            acao = next(a for a in self.TECLAS if self._codigos[a] == codigo)
            self._tecla(acao, False)
            self._fisicas.discard(codigo)

    def soltar_tudo(self):
        try:
            agora = time.monotonic()
            for acao in list(self.apertadas):
                self._soltou_em[acao] = agora
            for codigo in list(self._fisicas):  # soltar é seguro com qualquer foco
                acao = next(a for a in self.TECLAS if self._codigos[a] == codigo)
                self._tecla(acao, False)
            self._fisicas.clear()
            self.display.flush()
            self._mandar_ao_plugin(())
        except Exception:
            pass
        self.apertadas.clear()
        self._ativas.clear()

    def passo(self, acoes):
        self.aviso_controle = None
        if not self.controlando or self.janela is None or self.aviso:
            self.soltar_tudo()
            return
        desejadas = dict(acoes)
        # Direções opostas juntas não fazem sentido: fica só a mais forte. A que já
        # está apertada leva vantagem, senão o boneco fica trocando de lado
        for a, b in OPOSTAS:
            forca_a = acoes[a] + (0.2 if a in self._ativas else 0.0)
            forca_b = acoes[b] + (0.2 if b in self._ativas else 0.0)
            desejadas[a if forca_a < forca_b else b] = 0.0
        try:
            foco = self._foco()
            if foco != self.janela.id and not self.pelo_plugin:
                self.soltar_tudo()  # nunca deixa tecla segurada fora do jogo
                if any(desejadas[a] > self.APERTAR for a in self.TECLAS):
                    if foco in self.janelas_proprias:
                        self.focar()  # você clicou no painel: devolve o foco ao jogo
                    else:
                        self.aviso_controle = "Clique na janela do jogo para a mosca jogar"
                return
            agora = time.monotonic()
            for acao in self.TECLAS:
                apertar = self._decidir(acao, desejadas[acao], agora)
                if apertar != (acao in self.apertadas):
                    (self.apertadas.add if apertar else self.apertadas.discard)(acao)
                    if apertar:
                        self._apertou_em[acao] = agora
                    else:
                        self._soltou_em[acao] = agora
            self._sincronizar()
            self.display.flush()
        except Exception:
            self.soltar_tudo()
            self.janela = None

    def _decidir(self, acao, vontade, agora):
        """A tecla deve estar apertada agora? Histerese na vontade, toques
        repetidos (TOQUE_S) e tempo mínimo segurada (SEGURAR_MINIMO_S)."""
        limiar = self.SOLTAR if acao in self._ativas else self.APERTAR
        ativa = vontade > limiar
        if ativa and acao not in self._ativas:
            self._desde[acao] = agora
        (self._ativas.add if ativa else self._ativas.discard)(acao)
        if acao in TOQUE_S:
            return ativa and (agora - self._desde[acao]) % TOQUE_S[acao] < DURACAO_TOQUE_S
        if acao in SEGURAR_MAXIMO_S:
            if agora < self._solto_ate.get(acao, 0.0):
                return False  # o instante solta entre um pulo e o próximo
            if acao in self.apertadas and agora - self._apertou_em[acao] >= SEGURAR_MAXIMO_S[acao]:
                self._solto_ate[acao] = agora + SOLTO_S
                return False
        if acao in SEGURAR_MINIMO_S and not ativa and acao in self.apertadas:
            return agora - self._apertou_em[acao] < SEGURAR_MINIMO_S[acao]
        return ativa

    def _procurar(self, w):
        try:
            nome = w.get_wm_name()
        except Exception:
            nome = None
        # Nome exato: "contém" pegaria, por exemplo, uma aba "Hollow Knight - Wiki"
        # do navegador, e as teclas iriam parar lá
        if nome == self.nome:
            return w
        for filho in w.query_tree().children:
            achada = self._procurar(filho)
            if achada:
                return achada
        return None

    def _minimizada(self):
        prop = self.janela.get_full_property(self._wm_state, self._X.AnyPropertyType)
        return prop is not None and prop.value[0] == 3  # IconicState

    def quadro(self):
        try:
            if self.janela is None:
                self.janela = self._procurar(self.display.screen().root)
                if self.janela is None:
                    self.aviso = f"Janela \"{self.nome}\" não encontrada"
                    return self._vazio
            if self._minimizada():
                self.aviso = f"{self.nome} está minimizado"
                return self._vazio
            g = self.janela.get_geometry()
            raw = self.janela.get_image(0, 0, g.width, g.height, self._X.ZPixmap, 0xFFFFFFFF)
        except Exception:  # janela fechou ou mudou: procura de novo no próximo quadro
            self.janela = None
            self.aviso = f"Janela \"{self.nome}\" não encontrada"
            return self._vazio
        self.aviso = None
        bgra = np.frombuffer(raw.data, np.uint8).reshape(g.height, g.width, 4)
        # O Wine desenha barra de título e borda; o filho marca onde começa o jogo
        filhos = self.janela.query_tree().children
        bx, by = (filhos[0].get_geometry().x, filhos[0].get_geometry().y) if filhos else (0, 0)
        bgra = bgra[by : g.height - bx, bx : g.width - bx]
        return bgra[::2, ::2, 2::-1]  # BGRA -> RGB, metade da resolução
