"""Correção ao vivo: a mosca joga e você assume quando ela erra.

Com o "Controlar jogo" ligado, uma tecla do jogo apertada por você (e não pela
mosca) passa o controle para você: a mosca solta tudo e o seu trecho é gravado
como correção (gravacoes/<data>_correcao, com mais peso no treino). Depois de
SOLTOU_S sem você apertar nada, a mosca volta a jogar.

- Toque sem querer: menos de MINIMO_S apertando é descartado.
- Se a mosca estava em apuros (presa, loop, parada, dano ou morte nos últimos
  APUROS_S), a ajuda vira um estímulo ruim no último quadro dela: ela aprende o
  que evitar. Se você assumiu sem nada disso, não há punição.
"""

APUROS = {"presa", "loop", "parada", "dano", "morte"}


class Correcao:
    SOLTOU_S = 2.0
    MINIMO_S = 1.0
    APUROS_S = 5.0
    PUNICAO = -1.0

    def __init__(self):
        self.ativa = False
        self.inicio = self.ultima_tecla = None
        self.em_apuros = False  # no momento em que você assumiu
        self._apuros_ate = float("-inf")

    def eventos(self, eventos, agora):
        """Eventos de um quadro em que a mosca jogava."""
        if APUROS.intersection(eventos):
            self._apuros_ate = agora + self.APUROS_S

    def passo(self, voce_apertando, agora):
        """Um quadro com o jogo em foco. Devolve "assumiu", "devolveu" (uma
        correção de verdade), "sem_querer" (toque curto, descartar) ou None."""
        if voce_apertando:
            self.ultima_tecla = agora
            if not self.ativa:
                self.ativa, self.inicio = True, agora
                self.em_apuros = agora <= self._apuros_ate
                return "assumiu"
            return None
        if self.ativa and agora - self.ultima_tecla >= self.SOLTOU_S:
            return self.terminar()
        return None

    def terminar(self):
        """Fim da correção (soltou o teclado ou desligou a mosca)."""
        if not self.ativa:
            return None
        self.ativa = False
        self._apuros_ate = float("-inf")
        return "devolveu" if self.ultima_tecla - self.inicio >= self.MINIMO_S else "sem_querer"

    @property
    def segundos(self):
        """Duração da correção que acabou de terminar (até a última tecla)."""
        return self.ultima_tecla - self.inicio
