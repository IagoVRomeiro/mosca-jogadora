// Mosca jogadora: o "juiz" de dentro do jogo. A mosca continua vendo só a tela;
// este plugin só conta ao painel o que aconteceu (vida, geo, golpes, sala...).
//
// 30 vezes por segundo manda um JSON por UDP para 127.0.0.1:47123 com o estado
// atual e contadores que só crescem (golpes, inimigos mortos): se um pacote se
// perder, a diferença aparece no próximo.
//
// "acoes": as ações do jogo acionadas agora, como o próprio jogo as lê, venham
// do teclado ou do controle. Assim você pode ajudar a mosca pelo controle: ela
// aprende "Pular", não "botão A" nem "Space".
//
// Teclas da mosca: o painel manda para 127.0.0.1:47124 as ações que ela segura
// ("Esquerda,Pular"; vazio = nada) ~30x/s, e o plugin as aciona por dentro, como
// mais uma tecla. Assim ela joga mesmo com o jogo fora de foco (o XTest só digita
// na janela em foco). Sem pacote por SOLTAR_S, solta tudo (painel fechou ou travou).
// O pacote começa com "1|" se a mosca está no controle ("0|" desligada).
//
// Salão dos Deuses: quando a mosca volta de uma luta escolhida numa estátua
// (perdendo ou vencendo), o plugin abre o desafio (Cima) e entra de novo no
// mesmo nível, sem você precisar colocá-la. Só com a mosca no controle.
// Currículo: o painel pode pedir outra estátua (terceiro campo do pacote:
// "1|Esquerda|GG_Statue_Gorb") e o nível (quarto: 0 Sintonizado, 1 Ascendido,
// 2 Radiante); o plugin leva o Cavaleiro até ela e entra nesse nível. O plugin
// conta ao painel as estátuas liberadas ("estatuas", da esquerda para a direita)
// e o resultado de cada luta de chefe, de estátua ou de panteão ("lutas":
// [número, estátua ("" no panteão), sala, venceu]).
//
// Panteões: terminado um panteão iniciado por você (perdendo ou vencendo), ela
// volta à porta dele e o plugin o recomeça, do mesmo jeito que nas estátuas. A
// cada PANTEOES_S ele manda os panteões e as salas de cada um ("panteoes").
using System.Globalization;
using System.Net.Sockets;
using System.Text;
using BepInEx;
using HarmonyLib;
using UnityEngine;

[BepInPlugin("mosca.jogadora.eventos", "Mosca jogadora: eventos", "1.0.0")]
public class Plugin : BaseUnityPlugin
{
    internal static int golpes, inimigosMortos, chefesDerrotados;
    // Vida tirada de chefes, em milésimos de um chefe inteiro (cresce, como golpes)
    internal static int danoChefe;
    // Os últimos inimigos mortos (número do abate, nome do objeto): o nome na cena
    // é fixo, então dá para saber que é o mesmo inimigo renascido
    internal static readonly System.Collections.Generic.List<(int, string)> mortos =
        new System.Collections.Generic.List<(int, string)>();
    // Vida de cada inimigo no primeiro golpe que levou: chefe fora do Salão dos
    // Deuses é quem começou a luta com pelo menos VIDA_DE_CHEFE
    internal static readonly System.Collections.Generic.Dictionary<HealthManager, int> vidaInicial =
        new System.Collections.Generic.Dictionary<HealthManager, int>();
    internal const int VIDA_DE_CHEFE = 200;
    const int PORTA = 47123, PORTA_TECLAS = 47124;
    const float SOLTAR_S = 0.25f;
    UdpClient udp, teclas;
    float proximo, teclasEm = float.NegativeInfinity;
    int pacotesDeTeclas;  // lidos até agora: o painel vê que as teclas estão chegando
    // ações do jogo que a mosca está segurando agora (lidas por AcionarDaMosca)
    internal static readonly System.Collections.Generic.HashSet<InControl.PlayerAction> daMosca =
        new System.Collections.Generic.HashSet<InControl.PlayerAction>();
    internal static bool moscaNoControle;
    // a última luta escolhida numa estátua (BossChallengeUI.LoadBoss) e a volta depois de perder
    internal static int nivelEscolhido = -1;
    internal static string estatuaEscolhida;
    internal static bool morreuNaLuta, repetindo;
    // perder no Salão dos Deuses não é "dead": o Cavaleiro acorda do sonho. Perdeu =
    // entrou na luta e voltou à sala das estátuas sem a luta terminar (EndBossScene)
    internal static bool lutaEmCurso, entrouNaLuta, venceuLuta;
    static string salaDaLuta;  // a arena da luta de chefe em andamento (estátua ou panteão)
    // panteão iniciado por você numa porta (BossDoorChallengeUI.Begin) e a volta à porta
    internal static bool panteaoEmCurso, entrouNoPanteao, voltouDoPanteao, voltaDoPanteao;
    internal static string portaEscolhida;
    static string panteoesJson = "";
    float panteoesEm = -10f, panteoesMandadosEm = -10f;
    const float PANTEOES_S = 5f;
    internal static int derrotas;  // lutas perdidas no Salão (o painel conta como morte)
    internal static string estatuaAlvo = "", alvoDaVez;  // pedida pelo painel; a desta volta
    internal static int nivelPedido = -1;  // pelo painel (-1: o que você escolheu na estátua)
    internal static int numeroDaLuta;
    internal static readonly System.Collections.Generic.List<(int, string, string, bool)> lutas =
        new System.Collections.Generic.List<(int, string, string, bool)>();
    static string estatuasJson = "";
    float estatuasEm = -10f;
    // segurando: da volta até entrar na luta, as teclas dela não passam (andando, ela
    // saía de perto da estátua e o Cima não abria o desafio; no desafio, apertaria opções)
    internal static bool segurando;
    float voltouEm = -1f, proximoCima, segurandoAte;
    static float cimaAte;  // o Cima do próprio plugin (não aparece como seu em "acoes")
    int tentativas;
    // o Cavaleiro volta deitado e só levanta com um botão: o primeiro Cima o levanta,
    // um dos seguintes abre o desafio
    const float ESPERA_VOLTA_S = 1.5f, CIMA_S = 0.3f, ENTRE_CIMAS_S = 1.2f, SEGURAR_MAX_S = 15f;
    const int TENTATIVAS = 8;

    void Awake()
    {
        udp = new UdpClient();
        udp.Connect("127.0.0.1", PORTA);
        teclas = new UdpClient(new System.Net.IPEndPoint(System.Net.IPAddress.Loopback, PORTA_TECLAS));
        teclas.Client.Blocking = false;
        // o jogo continua rodando e lendo as teclas fora de foco
        Application.runInBackground = true;
        new Harmony("mosca.jogadora.eventos").PatchAll(typeof(Plugin).Assembly);
        Logger.LogInfo($"Mosca jogadora: mandando eventos para a porta {PORTA}");
    }

    // nome no painel (mosca/config.py) -> ação do jogo
    static readonly (string nome, System.Func<HeroActions, InControl.PlayerAction> acao)[] ACOES =
    {
        ("Esquerda", a => a.left), ("Direita", a => a.right), ("Cima", a => a.up), ("Baixo", a => a.down),
        ("Pular", a => a.jump), ("Atacar", a => a.attack), ("Esquiva", a => a.dash),
        ("Foco", a => a.focus), ("Foco", a => a.cast), ("Super Investida", a => a.superDash),
        ("Ferrão dos Sonhos", a => a.dreamNail), ("Magia Rápida", a => a.quickCast), ("Mapa", a => a.quickMap),
        ("Pausar", a => a.pause),  // Esc ou Start do controle: o painel tira a mosca do jogo
    };

    // O inimigo vivo mais perto do Cavaleiro: [dx, dy] (positivo: à direita / acima),
    // para o painel saber se um golpe ou uma magia tem para onde ir
    static string InimigoMaisPerto(HeroController hc)
    {
        if (hc == null) return "null";
        var eu = hc.transform.position;
        HealthManager perto = null;
        float melhor = float.MaxValue;
        foreach (var hm in FindObjectsByType<HealthManager>(FindObjectsSortMode.None))
        {
            if (hm == null || hm.isDead || hm.hp <= 0 || !hm.gameObject.activeInHierarchy) continue;
            var d = (hm.transform.position - eu).sqrMagnitude;
            if (d < melhor) { melhor = d; perto = hm; }
        }
        if (perto == null) return "null";
        var dif = perto.transform.position - eu;
        var c = CultureInfo.InvariantCulture;
        return $"[{dif.x.ToString("F2", c)},{dif.y.ToString("F2", c)}]";
    }

    // A lista dos panteões é grande: vai só a cada PANTEOES_S
    string MandarPanteoes()
    {
        if (panteoesJson == "" || Time.unscaledTime - panteoesMandadosEm < PANTEOES_S) return "";
        panteoesMandadosEm = Time.unscaledTime;
        return ",\"panteoes\":[" + panteoesJson + "]";
    }

    // As estátuas liberadas (com níveis), da esquerda para a direita
    static System.Collections.Generic.List<BossStatue> Estatuas()
    {
        var lista = new System.Collections.Generic.List<BossStatue>();
        foreach (var e in FindObjectsByType<BossStatue>(FindObjectsSortMode.None))
            if (e != null && !e.hasNoTiers && !e.isHidden && e.dreamReturnGate != null && e.StatueState.isUnlocked)
                lista.Add(e);
        lista.Sort((a, b) => a.transform.position.x.CompareTo(b.transform.position.x));
        return lista;
    }

    // Currículo: leva o Cavaleiro para a frente de outra estátua (onde ele acordaria
    // depois da luta dela) para o Cima abrir o desafio dela
    static bool IrParaEstatua(HeroController hc, string nome)
    {
        foreach (var e in Estatuas())
        {
            if (e.gameObject.name != nome) continue;
            hc.transform.position = e.dreamReturnGate.transform.position;
            var corpo = hc.GetComponent<Rigidbody2D>();
            if (corpo != null) corpo.linearVelocity = Vector2.zero;
            if (GameCameras.instance != null && GameCameras.instance.cameraController != null)
                GameCameras.instance.cameraController.PositionToHero(false);
            return true;
        }
        return false;
    }

    // Os panteões (portas do GG_Atrium) e as salas de cada um, para o painel saber
    // quando os chefes de um panteão já foram dominados nas estátuas
    void AtualizarPanteoes(GameManager gm)
    {
        if (gm == null || gm.sceneName != "GG_Atrium" || Time.unscaledTime - panteoesEm < 2f) return;
        panteoesEm = Time.unscaledTime;
        var partes = new System.Collections.Generic.List<string>();
        foreach (var porta in FindObjectsByType<BossSequenceDoor>(FindObjectsSortMode.None))
        {
            if (porta == null || porta.bossSequence == null) continue;
            var salas = new System.Collections.Generic.List<string>();
            for (int i = 0; i < porta.bossSequence.Count; i++)
                salas.Add("\"" + (porta.bossSequence.GetSceneAt(i) ?? "").Replace("\"", "") + "\"");
            partes.Add($"{{\"porta\":\"{porta.gameObject.name.Replace("\"", "")}\",\"liberado\":{(porta.CurrentCompletion.unlocked ? "true" : "false")},\"salas\":[{string.Join(",", salas)}]}}");
        }
        var json = string.Join(",", partes);
        if (json != panteoesJson)
            Logger.LogInfo($"Mosca jogadora: {partes.Count} panteões encontrados");
        panteoesJson = json;
    }

    void AtualizarEstatuas(GameManager gm)
    {
        if (gm == null || gm.sceneName != "GG_Workshop" || Time.unscaledTime - estatuasEm < 2f) return;
        estatuasEm = Time.unscaledTime;
        var lista = Estatuas();
        var json = string.Join(",", lista.ConvertAll(e => "\"" + e.gameObject.name.Replace("\"", "") + "\""));
        if (json != estatuasJson)
            Logger.LogInfo($"Mosca jogadora: {lista.Count} estátuas liberadas para o currículo");
        estatuasJson = json;
    }

    // Teclas da mosca: o K é Foco e Magia ao mesmo tempo (segurar cura, tocar solta
    // magia), como no teclado; a Magia não está em ACOES porque o jogo a vê como Foco
    static System.Collections.Generic.IEnumerable<InControl.PlayerAction> AcoesDe(string nome, HeroActions a)
    {
        if (nome == "Magia") nome = "Foco";
        foreach (var (n, acao) in ACOES)
            if (n == nome) yield return acao(a);
    }

    void LerTeclasDaMosca()
    {
        // Lê a fila até esvaziar (fica o último). Não usa teclas.Available: no Wine ela
        // é sempre 0 e nada era lido; sem pacote, o socket não bloqueante dá exceção
        string ultimo = null;
        var buf = new byte[1024];
        while (true)
        {
            try
            {
                System.Net.EndPoint de = new System.Net.IPEndPoint(System.Net.IPAddress.Any, 0);
                ultimo = Encoding.UTF8.GetString(buf, 0, teclas.Client.ReceiveFrom(buf, ref de));
                pacotesDeTeclas++;
            }
            catch (SocketException) { break; }
        }
        var ih = InputHandler.Instance;
        if (ultimo != null && ih != null && ih.inputActions != null)
        {
            teclasEm = Time.unscaledTime;
            daMosca.Clear();
            var partes = ultimo.Split('|');  // painel antigo: só as ações
            moscaNoControle = partes.Length < 2 || partes[0] == "1";
            estatuaAlvo = partes.Length >= 3 ? partes[2] : "";
            nivelPedido = partes.Length >= 4 && int.TryParse(partes[3], out var n) ? n : -1;
            foreach (var nome in partes[partes.Length >= 2 ? 1 : 0].Split(','))
                foreach (var acao in AcoesDe(nome, ih.inputActions)) daMosca.Add(acao);
        }
        else if (Time.unscaledTime - teclasEm > SOLTAR_S)
        {
            daMosca.Clear();
            moscaNoControle = false;
        }
        if (segurando) daMosca.Clear();
        if (ih != null && ih.inputActions != null && Time.unscaledTime < cimaAte) daMosca.Add(ih.inputActions.up);
    }

    // Toda luta de chefe que termina (a arena some): vitória se o jogo chamou
    // EndBossScene nela. Vale para as estátuas e para os panteões
    void FimDeLuta(GameManager gm)
    {
        // a sala da luta acabou (outra sala, ou fora de arena): no panteão um chefe
        // pode vir logo depois do outro, sem nenhum quadro fora de arena no meio
        var sala = BossSceneController.IsBossScene && gm != null ? gm.sceneName : null;
        if (salaDaLuta != null && sala != salaDaLuta)
        {
            if (!venceuLuta) derrotas++;
            lutas.Add((++numeroDaLuta, lutaEmCurso ? estatuaEscolhida ?? "" : "", salaDaLuta, venceuLuta));
            if (lutas.Count > 8) lutas.RemoveAt(0);
            salaDaLuta = null;
        }
        if (sala != null && salaDaLuta == null)
        {
            salaDaLuta = sala;
            venceuLuta = false;
        }
    }

    void VoltarParaALuta(GameManager gm, HeroController hc)
    {
        if (gm == null || hc == null) return;
        var agora = Time.unscaledTime;
        if (lutaEmCurso && BossSceneController.IsBossScene) entrouNaLuta = true;
        if (segurando && (BossSceneController.IsBossScene || BossSequenceController.IsInSequence || agora > segurandoAte))
            segurando = repetindo = false;
        if (panteaoEmCurso && BossSequenceController.IsInSequence) entrouNoPanteao = true;
        if (panteaoEmCurso && entrouNoPanteao && !BossSequenceController.IsInSequence && gm.sceneName == "GG_Atrium")
        {
            panteaoEmCurso = entrouNoPanteao = false;
            voltouDoPanteao = true;  // perdendo ou vencendo, recomeça o panteão
        }
        if (lutaEmCurso && entrouNaLuta && !BossSceneController.IsBossScene && gm.sceneName == "GG_Workshop")
        {
            lutaEmCurso = entrouNaLuta = false;
            morreuNaLuta = true;  // perdendo ou vencendo, volta para a luta

        }
        if (!moscaNoControle)  // você desligou a mosca: fica onde está, com você
        {
            morreuNaLuta = voltouDoPanteao = repetindo = segurando = false;
            return;
        }
        if ((morreuNaLuta && gm.sceneName == "GG_Workshop") || (voltouDoPanteao && gm.sceneName == "GG_Atrium"))
        {
            if (!segurando) segurandoAte = agora + SEGURAR_MAX_S;
            segurando = true;  // desde já: acordando, ela não sai andando
            if (hc.cState.dead) { voltouEm = -1f; return; }
            if (voltouEm < 0) voltouEm = agora;
            if (agora - voltouEm < ESPERA_VOLTA_S) return;  // a sala terminando de aparecer
            voltaDoPanteao = voltouDoPanteao;
            morreuNaLuta = voltouDoPanteao = false;
            voltouEm = -1f;
            repetindo = true;
            tentativas = 0;
            proximoCima = agora;
            if (voltaDoPanteao)
            {
                alvoDaVez = portaEscolhida;
                Logger.LogInfo($"Mosca jogadora: recomeçando o panteão {alvoDaVez}");
                return;
            }
            alvoDaVez = estatuaEscolhida;
            if (!string.IsNullOrEmpty(estatuaAlvo) && estatuaAlvo != estatuaEscolhida && IrParaEstatua(hc, estatuaAlvo))
                alvoDaVez = estatuaAlvo;
            Logger.LogInfo($"Mosca jogadora: de volta à luta de {alvoDaVez} (nível {(nivelPedido >= 0 ? nivelPedido : nivelEscolhido) + 1})");
        }
        if (repetindo && agora >= proximoCima)  // Cima até o desafio abrir (AoAbrirDesafio)
        {
            if (tentativas >= TENTATIVAS)
            {
                repetindo = segurando = false;
                Logger.LogInfo("Mosca jogadora: o desafio não abriu; ela segue sozinha");
                return;
            }
            tentativas++;
            cimaAte = agora + CIMA_S;
            proximoCima = agora + ENTRE_CIMAS_S;
        }
    }

    static string Acoes()
    {
        var ih = InputHandler.Instance;
        if (ih == null || ih.inputActions == null) return "";
        var nomes = new System.Collections.Generic.List<string>();
        foreach (var (nome, acao) in ACOES)
        {
            var a = acao(ih.inputActions);
            if (nome == "Cima" && Time.unscaledTime < cimaAte + 0.3f) continue;  // o do plugin, não o seu
            if (a != null && a.IsPressed && !nomes.Contains(nome)) nomes.Add(nome);
        }
        return string.Join(",", nomes.ConvertAll(n => "\"" + n + "\""));
    }

    void Update()
    {
        // a InControl para de ler as teclas fora de foco se isto estiver ligado
        InControl.InputManager.SuspendInBackground = false;
        LerTeclasDaMosca();
        FimDeLuta(GameManager.instance);
        VoltarParaALuta(GameManager.instance, HeroController.instance);
        AtualizarEstatuas(GameManager.instance);
        AtualizarPanteoes(GameManager.instance);
        if (Time.unscaledTime < proximo) return;
        proximo = Time.unscaledTime + 1f / 30f;
        var pd = PlayerData.instance;
        if (pd == null) return;
        var hc = HeroController.instance;
        var gm = GameManager.instance;
        Vector3 pos = hc != null ? hc.transform.position : Vector3.zero;
        Vector2 vel = hc != null ? hc.current_velocity : Vector2.zero;
        var s = hc != null ? hc.cState : null;
        var c = CultureInfo.InvariantCulture;
        var json = new StringBuilder(256)
            .Append("{\"cena\":\"").Append(gm != null ? (gm.sceneName ?? "").Replace("\"", "") : "").Append('"')
            .Append(",\"x\":").Append(pos.x.ToString("F2", c))
            .Append(",\"y\":").Append(pos.y.ToString("F2", c))
            .Append(",\"vx\":").Append(vel.x.ToString("F2", c))
            .Append(",\"vy\":").Append(vel.y.ToString("F2", c))
            .Append(",\"vida\":").Append(pd.health)
            .Append(",\"vida_max\":").Append(pd.maxHealth)
            .Append(",\"vida_azul\":").Append(pd.healthBlue)
            .Append(",\"geo\":").Append(pd.geo)
            .Append(",\"alma\":").Append(pd.MPCharge)
            .Append(",\"golpes\":").Append(golpes)
            .Append(",\"inimigos_mortos\":").Append(inimigosMortos)
            .Append(",\"chefes_derrotados\":").Append(chefesDerrotados)
            .Append(",\"derrotas\":").Append(derrotas)
            .Append(",\"inimigo\":").Append(InimigoMaisPerto(hc))
            .Append(",\"olhando_direita\":").Append(hc != null && hc.cState.facingRight ? "true" : "false")
            .Append(",\"estatuas\":[").Append(estatuasJson).Append(']')
            .Append(MandarPanteoes())
            .Append(",\"lutas\":[").Append(string.Join(",", lutas.ConvertAll(l => $"[{l.Item1},\"{l.Item2.Replace("\"", "")}\",\"{l.Item3.Replace("\"", "")}\",{(l.Item4 ? 1 : 0)}]"))).Append(']')
            .Append(",\"dano_chefe\":").Append(danoChefe)
            .Append(",\"mortos\":[").Append(string.Join(",", mortos.ConvertAll(m => $"[{m.Item1},\"{m.Item2.Replace("\"", "")}\"]"))).Append(']')
            // sombra esperando no mapa (morreu e não foi buscar) e o geo que ela guarda
            .Append(",\"sombra\":").Append(pd.soulLimited ? "true" : "false")
            .Append(",\"geo_sombra\":").Append(pd.geoPool)
            .Append(",\"morta\":").Append(s != null && s.dead ? "true" : "false")
            .Append(",\"no_chao\":").Append(s != null && s.onGround ? "true" : "false")
            .Append(",\"na_parede\":").Append(s != null && s.wallSliding ? "true" : "false")
            .Append(",\"curando\":").Append(s != null && s.focusing ? "true" : "false")
            .Append(",\"acoes\":[").Append(Acoes()).Append(']')
            .Append(",\"entrada\":").Append(pacotesDeTeclas)  // pacotes de teclas da mosca lidos
            // ponto de retorno (o último banco em que descansou) e cair em espinhos/ácido
            .Append(",\"banco\":\"").Append(((pd.respawnScene ?? "") + "|" + (pd.respawnMarkerName ?? "")).Replace("\"", "")).Append('"')
            .Append(",\"perigo\":").Append(s != null && (s.hazardDeath || s.hazardRespawning) ? "true" : "false")
            .Append('}').ToString();
        try
        {
            var dados = Encoding.UTF8.GetBytes(json);
            udp.Send(dados, dados.Length);
        }
        catch (SocketException) { }  // painel fechado: tudo bem
    }
}

// A mosca segurando uma ação: entra como mais uma tecla, junto das de verdade
// (a InControl fica com a mais forte de todas no quadro)
[HarmonyPatch(typeof(InControl.PlayerAction), "UpdateBindings")]
static class AcionarDaMosca
{
    static void Prefix(InControl.PlayerAction __instance, ulong updateTick, float deltaTime)
    {
        if (Plugin.daMosca.Contains(__instance)) __instance.UpdateWithValue(1f, updateTick, deltaTime);
    }
}

// A luta escolhida numa estátua do Salão dos Deuses: qual estátua e qual nível
[HarmonyPatch(typeof(BossChallengeUI), "LoadBoss", typeof(int), typeof(bool))]
static class AoEscolherLuta
{
    internal static readonly AccessTools.FieldRef<BossChallengeUI, BossStatue> estatua =
        AccessTools.FieldRefAccess<BossChallengeUI, BossStatue>("bossStatue");

    static void Prefix(BossChallengeUI __instance, int level)
    {
        var e = estatua(__instance);
        Plugin.nivelEscolhido = level;
        Plugin.estatuaEscolhida = e != null ? e.gameObject.name : null;
        Plugin.morreuNaLuta = Plugin.entrouNaLuta = false;
        Plugin.lutaEmCurso = true;
    }
}

// Venceu a luta (todos os chefes mortos): a volta para as estátuas não é derrota
[HarmonyPatch(typeof(BossSceneController), "EndBossScene")]
static class AoVencerLuta
{
    static void Prefix() => Plugin.venceuLuta = true;
}

// O desafio abriu depois de a mosca perder: entra de novo no mesmo nível
[HarmonyPatch(typeof(BossChallengeUI), "Setup")]
static class AoAbrirDesafio
{
    static void Postfix(BossChallengeUI __instance, BossStatue bossStatue)
    {
        if (!Plugin.repetindo || Plugin.voltaDoPanteao || bossStatue == null || bossStatue.hasNoTiers) return;
        Plugin.repetindo = false;  // abriu: para de apertar Cima (segue segurando até a luta)
        if (bossStatue.gameObject.name != Plugin.alvoDaVez || Plugin.nivelEscolhido < 0)
        {
            Plugin.segurando = false;
            return;
        }
        __instance.StartCoroutine(Entrar(__instance, Plugin.nivelPedido >= 0 ? Plugin.nivelPedido : Plugin.nivelEscolhido));
    }

    static System.Collections.IEnumerator Entrar(BossChallengeUI ui, int nivel)
    {
        yield return new WaitForSeconds(0.6f);  // a tela termina de abrir
        if (ui != null && ui.gameObject.activeInHierarchy) ui.LoadBoss(nivel);
    }
}

// Panteão iniciado numa porta: qual (para recomeçar o mesmo depois)
[HarmonyPatch(typeof(BossDoorChallengeUI), "Begin")]
static class AoComecarPanteao
{
    internal static readonly AccessTools.FieldRef<BossDoorChallengeUI, BossSequenceDoor> porta =
        AccessTools.FieldRefAccess<BossDoorChallengeUI, BossSequenceDoor>("door");

    static void Prefix(BossDoorChallengeUI __instance)
    {
        var p = porta(__instance);
        Plugin.portaEscolhida = p != null ? p.gameObject.name : null;
        Plugin.panteaoEmCurso = Plugin.portaEscolhida != null;
        Plugin.entrouNoPanteao = Plugin.voltouDoPanteao = false;
    }
}

// A tela da porta abriu depois do panteão terminar: começa o mesmo de novo
[HarmonyPatch(typeof(BossDoorChallengeUI), "Setup")]
static class AoAbrirPorta
{
    static void Postfix(BossDoorChallengeUI __instance, BossSequenceDoor door)
    {
        if (!Plugin.repetindo || !Plugin.voltaDoPanteao || door == null) return;
        Plugin.repetindo = false;  // abriu: para de apertar Cima (segue segurando até começar)
        if (door.gameObject.name != Plugin.alvoDaVez)
        {
            Plugin.segurando = false;
            return;
        }
        __instance.StartCoroutine(Comecar(__instance));
    }

    static System.Collections.IEnumerator Comecar(BossDoorChallengeUI ui)
    {
        yield return new WaitForSeconds(0.8f);  // a tela termina de abrir
        if (ui != null && ui.gameObject.activeInHierarchy) ui.Begin();
    }
}

// Golpe que tirou vida de um inimigo (TakeDamage: o Hit pode ser bloqueado)
[HarmonyPatch(typeof(HealthManager), "TakeDamage")]
static class AoAcertar
{
    static void Prefix(HealthManager __instance, out int __state)
    {
        if (!Plugin.vidaInicial.ContainsKey(__instance)) Plugin.vidaInicial[__instance] = __instance.hp;
        __state = __instance.hp;
    }

    static void Postfix(HealthManager __instance, int __state)
    {
        Plugin.golpes++;
        // dano no chefe aos poucos: a fração da vida inicial dele que este golpe tirou
        if (AoMatar.EhChefe(__instance) && Plugin.vidaInicial.TryGetValue(__instance, out var vida) && vida > 0)
            Plugin.danoChefe += System.Math.Max(0, System.Math.Min(__state, vida) - System.Math.Max(0, __instance.hp)) * 1000 / vida;
    }
}

// Inimigo morto (uma vez só por inimigo)
[HarmonyPatch(typeof(HealthManager), "Die")]
static class AoMatar
{
    static void Prefix(HealthManager __instance, out bool __state) => __state = __instance.isDead;
    static void Postfix(HealthManager __instance, bool __state)
    {
        if (__state || !__instance.isDead) return;
        Plugin.inimigosMortos++;
        Plugin.mortos.Add((Plugin.inimigosMortos, __instance.gameObject.name));
        if (Plugin.mortos.Count > 8) Plugin.mortos.RemoveAt(0);
        if (EhChefe(__instance)) Plugin.chefesDerrotados++;
        Plugin.vidaInicial.Remove(__instance);
    }

    internal static bool EhChefe(HealthManager inimigo)
    {
        // No Salão dos Deuses o jogo sabe quais são os chefes da luta
        var luta = BossSceneController.Instance;
        if (luta != null && BossSceneController.IsBossScene && luta.bosses != null && System.Array.IndexOf(luta.bosses, inimigo) >= 0)
            return true;
        return Plugin.vidaInicial.TryGetValue(inimigo, out var vida) && vida >= Plugin.VIDA_DE_CHEFE;
    }
}
