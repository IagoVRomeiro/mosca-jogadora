"""Registro no Supabase contra um servidor falso local (nada sai do PC)."""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np

import registro


class ServidorFalso(BaseHTTPRequestHandler):
    pedidos = []
    recusar_mortes = False

    def log_message(self, *args):
        pass

    def _responder(self):
        corpo = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.pedidos.append((self.command, self.path, dict(self.headers), corpo))
        if self.recusar_mortes and self.path.startswith("/rest/v1/partidas_mosca") and b"mortes" in corpo:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"message":"column \\"mortes\\" does not exist"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if self.command == "GET" and "/rest/v1/sessoes" in self.path:
            self.wfile.write(json.dumps([{"id": "velha", "dados_arquivo": "velha.npz"}]).encode())
        elif self.command == "POST" and self.path.startswith("/rest/v1/treinos"):
            self.wfile.write(b'[{"id": 7}]')
        elif self.command == "POST" and self.path.startswith("/rest/v1/"):
            self.wfile.write(b"[]")
        elif self.command == "POST":
            self.wfile.write(b'{"Key": "ok"}')

    do_GET = do_POST = do_PATCH = _responder


class TesteRegistro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = HTTPServer(("127.0.0.1", 0), ServidorFalso)
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{cls.servidor.server_port}"
        cls.original = registro.Supabase.do_env
        registro.Supabase.do_env = classmethod(lambda c: c(url, "sb_secret_teste"))

    @classmethod
    def tearDownClass(cls):
        registro.Supabase.do_env = cls.original
        cls.servidor.shutdown()

    def setUp(self):
        ServidorFalso.pedidos.clear()
        ServidorFalso.recusar_mortes = False

    def sessao(self, pasta):
        pasta.mkdir(parents=True)
        np.savez(pasta / "parte_000.npz", telas=np.zeros((3, 90, 160), np.uint8),
                 teclas=np.zeros((3, 11), bool), recompensas=np.zeros(3, np.float32),
                 vidas=np.zeros(3, np.int8), acoes=np.array(["a"] * 11))

    def test_treino_envia_sessoes_novas_modelo_e_caminho(self):
        base = Path(tempfile.mkdtemp())
        for nome in ("velha", "nova"):
            self.sessao(base / nome)
        modelo = base / "modelo.npz"
        modelo.write_bytes(b"pesos")
        linhas = [{"id": "velha"}, {"id": "nova"}]
        mensagem, treino_id = registro.registrar_treino(
            linhas, {"quadros": 6}, modelo, {"velha": base / "velha", "nova": base / "nova"}
        )
        self.assertEqual(treino_id, 7)
        caminhos = [(m, c) for m, c, _, _ in ServidorFalso.pedidos]
        self.assertIn(("POST", "/storage/v1/object/sessoes/nova.npz"), caminhos)
        self.assertNotIn(("POST", "/storage/v1/object/sessoes/velha.npz"), caminhos)  # já estava lá
        self.assertIn(("POST", "/storage/v1/object/modelos/treino_00007.npz"), caminhos)
        self.assertIn(("PATCH", "/rest/v1/treinos?id=eq.7"), caminhos)
        for _, _, cabecalhos, _ in ServidorFalso.pedidos:
            cab = {k.lower(): v for k, v in cabecalhos.items()}
            self.assertEqual(cab["apikey"], "sb_secret_teste")
        # as telas não vão para a nuvem: o arquivo da sessão é pequeno
        nova = [c for m, p, _, c in ServidorFalso.pedidos if p.endswith("sessoes/nova.npz")][0]
        self.assertLess(len(nova), 3000)

    def test_partida_sem_coluna_mortes_ainda_e_registrada(self):
        ServidorFalso.recusar_mortes = True
        registro.registrar_partida({"segundos": 60, "mortes": 1, "danos": 2}).join(5)
        enviadas = [json.loads(c) for m, p, _, c in ServidorFalso.pedidos if p == "/rest/v1/partidas_mosca"]
        self.assertEqual(len(enviadas), 2)  # tentou com mortes, repetiu sem
        self.assertNotIn("mortes", enviadas[1][0])
        self.assertEqual(enviadas[1][0]["danos"], 2)  # o resto da partida foi junto

    def test_sem_env_nao_quebra(self):
        registro.Supabase.do_env = classmethod(lambda c: None)
        try:
            mensagem, treino_id = registro.registrar_treino([], {}, None, {})
        finally:
            url = f"http://127.0.0.1:{self.servidor.server_port}"
            registro.Supabase.do_env = classmethod(lambda c: c(url, "sb_secret_teste"))
        self.assertIsNone(treino_id)
        self.assertIn("desligado", mensagem)


if __name__ == "__main__":
    unittest.main()
