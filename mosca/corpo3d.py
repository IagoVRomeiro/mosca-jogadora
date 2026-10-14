"""A mosca 3D (FlyGym/MuJoCo) na frente de um PC, apertando as teclas com as patas."""

import collections
import threading
import time

import numpy as np

from .config import ACOES, ACOES_JOGO, PASSOS_FISICA_POR_QUADRO, QUADRO_MS


class MoscaNoPC:
    """A mosca na frente de um PC, apertando as teclas do jogo com as patas.

    O corpo fica preso (TetheredWorld) em cima do teclado; cada ação tem a sua
    tecla, perto da pata que a aperta (ver ACOES_JOGO). O monitor mostra o jogo
    ao vivo. Roda numa thread própria: o contexto OpenGL do MuJoCo não pode ficar
    na thread do Qt.
    """

    CAMERAS = ["Mesa", "Teclado", "Tela"]
    BATIDAS_HZ = 7.0  # velocidade com que a pata bate na tecla
    TELA = (640, 360)  # textura do monitor (altura, largura), já girada para o plano

    def __init__(self, resolucao=(540, 720)):
        self.acoes = {a: 0.0 for a in ACOES}
        self.imagem = None
        self.ultimo = np.zeros((*resolucao, 3), dtype=np.uint8)
        self.camera = "Mesa"
        self.batidas_por_s = 0.0
        self.erro = None  # mensagem para o painel se a simulação 3D quebrar
        self.rodando = True
        self._ultimo_render = 0.0
        self.thread = threading.Thread(target=self._loop, args=(resolucao,), daemon=True)
        self.thread.start()

    def _loop(self, resolucao):
        try:
            self._montar(resolucao)
            while self.rodando:
                inicio = time.monotonic()
                self._avancar()
                # No máximo tempo real: mais rápido só gasta CPU e acelera as patas
                passo_s = PASSOS_FISICA_POR_QUADRO * self.sim.timestep
                time.sleep(max(0.0, passo_s - (time.monotonic() - inicio)))
        except Exception as e:
            self.erro = f"Simulação 3D parou: {type(e).__name__}: {e}"
            raise
        finally:
            if hasattr(self, "mj_renderer"):
                self.mj_renderer.close()
            if hasattr(self, "sim"):
                self.sim.close()

    def parar(self):
        self.rodando = False
        self.thread.join()

    def _montar(self, resolucao):
        import mujoco
        from flygym import Simulation
        from flygym.compose.world.tethered_world import TetheredWorld
        from flygym.utils.math import Rotation3D
        from flygym_demo.complex_terrain import (
            PreprogrammedSteps,
            get_default_locomotion_dof_order,
            make_locomotion_fly,
        )
        from flygym.compose import ActuatorType

        self._mujoco = mujoco
        self._tipo_atuador = ActuatorType.POSITION
        fly = make_locomotion_fly(name="mosca", add_adhesion=False, colorize=True)
        world = TetheredWorld()
        spec = world.mjcf_root
        for tex in spec.textures:
            if tex.name == "skybox":
                tex.rgb1, tex.rgb2 = [0.05, 0.05, 0.07], [0.0, 0.0, 0.0]
        wb = spec.worldbody
        caixa = mujoco.mjtGeom.mjGEOM_BOX
        sem_colisao = dict(contype=0, conaffinity=0)

        def objeto(pos, tamanho, cor, **kw):
            return wb.add_geom(type=caixa, pos=pos, size=tamanho, rgba=cor, **sem_colisao, **kw)

        objeto((0, 0, -0.85), (14, 26, 0.25), (0.13, 0.13, 0.15, 1))  # mesa
        objeto((-0.2, 0, -0.42), (3.0, 9.2, 0.18), (0.05, 0.05, 0.06, 1))  # base do teclado

        # Teclas: grade de 5 x 17; as das ações ficam embaixo das patas
        nomes_teclas = {}
        for x in range(-2, 3):
            for y in range(-8, 9):
                nome = f"tecla_{x}_{y}"
                objeto((x, y, -0.12), (0.42, 0.42, 0.12), (0.16, 0.16, 0.18, 1), name=nome)
                nomes_teclas[(x, y)] = nome

        # Monitor com o jogo (textura atualizada a cada quadro)
        th, tw = self.TELA
        tex = spec.add_texture(name="tela", type=mujoco.mjtTexture.mjTEXTURE_2D, width=tw, height=th, nchannel=3)
        tex.data = bytes(th * tw * 3)
        material = spec.add_material(name="tela", emission=1.0)
        material.textures[int(mujoco.mjtTextureRole.mjTEXROLE_RGB)] = "tela"
        wb.add_geom(
            type=mujoco.mjtGeom.mjGEOM_PLANE, pos=(8.0, 0, 5.2), size=(4.5, 8.0, 0.1),
            material="tela", euler=(0, -np.pi / 2, 0), **sem_colisao,
        )
        objeto((8.15, 0, 5.2), (0.12, 8.4, 4.9), (0.02, 0.02, 0.02, 1))  # moldura
        objeto((8.6, 0, -0.1), (0.25, 0.7, 0.6), (0.05, 0.05, 0.06, 1))  # haste
        objeto((8.6, 0, -0.55), (1.5, 2.5, 0.06), (0.05, 0.05, 0.06, 1))  # pé

        wb.add_light(pos=(-4, 6, 14), dir=(0.3, -0.4, -1), diffuse=(0.6, 0.6, 0.65), castshadow=True)
        wb.add_light(pos=(7, 0, 5), dir=(-1, 0, -0.3), diffuse=(0.25, 0.3, 0.45), castshadow=False)
        for nome, pos, alvo in (
            ("Mesa", (-14, 11, 9.5), (4, -0.5, 3)),
            ("Teclado", (-3.5, 4.5, 3.2), (0.6, 0, 0)),
            ("Tela", (-5, -1.8, 2.6), (8, 0.5, 4.5)),
        ):
            wb.add_camera(name=nome, **self._olhar(pos, alvo))

        world.add_fly(fly, [0, 0, 0], Rotation3D("quat", [1, 0, 0, 0]))
        self.sim = Simulation(world)
        modelo = self.sim.mj_model
        self.mj_renderer = mujoco.Renderer(modelo, *resolucao)
        self._tex_id = mujoco.mj_name2id(modelo, mujoco.mjtObj.mjOBJ_TEXTURE, "tela")
        adr = modelo.tex_adr[self._tex_id]
        self._tex = modelo.tex_data[adr : adr + th * tw * 3]

        def geom(nome):
            return mujoco.mj_name2id(modelo, mujoco.mjtObj.mjOBJ_GEOM, nome)

        self._tecla_geom = {nome: geom(nomes_teclas[a.posicao]) for nome, a in ACOES_JOGO.items()}
        self._tecla_z = modelo.geom_pos[next(iter(self._tecla_geom.values()))][2]

        self.passos = PreprogrammedSteps()
        self._ordem = get_default_locomotion_dof_order()
        self._pernas = list(self.passos.legs)
        self._reiniciar()

    @staticmethod
    def _olhar(pos, alvo):
        """Câmera em `pos` olhando para `alvo`."""
        pos, alvo = np.asarray(pos, float), np.asarray(alvo, float)
        z = (pos - alvo) / np.linalg.norm(pos - alvo)
        x = np.cross([0, 0, 1], z)
        x /= np.linalg.norm(x)
        return dict(pos=pos, xyaxes=np.concatenate([x, np.cross(z, x)]))

    def _reiniciar(self):
        self.sim.reset()
        self.sim.warmup()
        self.fases = np.full(len(self._pernas), np.pi)
        self.amplitudes = np.zeros(len(self._pernas))
        self._apertando = np.zeros(len(self._pernas), dtype=bool)
        self._batidas = collections.deque()

    def passo(self, acoes, imagem=None):
        """Chamado pela interface: guarda ações e a tela do jogo; devolve o último quadro."""
        self.acoes, self.imagem = acoes, imagem
        return self.ultimo

    def _mostrar_no_monitor(self):
        if self.imagem is None:
            return
        th, tw = self.TELA
        h, w = self.imagem.shape[:2]
        linhas = np.linspace(0, h - 1, tw).astype(int)
        colunas = np.linspace(0, w - 1, th).astype(int)
        quadro = self.imagem[linhas][:, colunas]  # redimensiona para tw x th
        self._tex[:] = np.rot90(quadro, -1).ravel()  # gira para casar com o plano
        self._mujoco.mjr_uploadTexture(self.sim.mj_model, self.mj_renderer._mjr_context, self._tex_id)

    def _avancar(self):
        acoes = self.acoes
        dt = PASSOS_FISICA_POR_QUADRO * self.sim.timestep
        acoes_ativas = [nome for nome in ACOES_JOGO if acoes[nome] > 0.5]
        ativas = np.zeros(len(self._pernas), dtype=bool)
        for nome in acoes_ativas:
            ativas[self._pernas.index(ACOES_JOGO[nome].pata)] = True

        # Pata ativa bate na tecla (ciclo de passo no lugar); as outras voltam ao repouso
        self.amplitudes += 0.35 * (ativas.astype(float) - self.amplitudes)
        self.fases[ativas] += 2 * np.pi * self.BATIDAS_HZ * dt
        angulos = self.passos.get_joint_angles_by_dof_order(self.fases, self.amplitudes, self._ordem)
        self.sim.set_actuator_inputs("mosca", self._tipo_atuador, angulos)
        for _ in range(PASSOS_FISICA_POR_QUADRO):
            self.sim.step()

        # Tecla afunda e acende quando a pata está na fase de apoio
        modelo = self.sim.mj_model
        apoio = self.passos.get_adhesion_onoff_by_phase(self.fases).astype(bool)
        apertando = ativas & apoio & (self.amplitudes > 0.5)
        agora = self.sim.time
        self._batidas.extend([agora] * np.count_nonzero(apertando & ~self._apertando))
        while self._batidas and self._batidas[0] < agora - 1.0:
            self._batidas.popleft()
        self.batidas_por_s = len(self._batidas)  # no último segundo (tempo simulado)
        self._apertando = apertando
        for nome, acao in ACOES_JOGO.items():
            g = self._tecla_geom[nome]
            batendo = nome in acoes_ativas and apertando[self._pernas.index(acao.pata)]
            modelo.geom_pos[g][2] = self._tecla_z - (0.09 if batendo else 0.0)
            if batendo:
                modelo.geom_rgba[g] = (1.0, 0.77, 0.27, 1)
            elif nome in acoes_ativas:
                modelo.geom_rgba[g] = (0.49, 0.36, 1.0, 1)
            else:
                modelo.geom_rgba[g] = (0.24, 0.24, 0.3, 1)  # teclas de ação um pouco mais claras
        self._mujoco.mj_kinematics(modelo, self.sim.mj_data)

        # Renderizar mais que a tela mostra (QUADRO_MS) só gasta CPU/GPU
        agora = time.monotonic()
        if agora - self._ultimo_render < QUADRO_MS / 1000:
            return
        self._ultimo_render = agora
        self._mostrar_no_monitor()
        self.mj_renderer.update_scene(self.sim.mj_data, camera=self.camera)
        self.ultimo = self.mj_renderer.render().copy()
