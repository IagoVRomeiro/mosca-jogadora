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
    internal static int derrotas;  // lutas perdidas no Salão (o painel conta como morte)
    float voltouEm = -1f, repetirAte, cimaAte;
    const float ESPERA_VOLTA_S = 2.5f, CIMA_S = 0.3f, DESISTE_S = 5f;

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
            var barra = ultimo.IndexOf('|');  // painel antigo: só as ações
            moscaNoControle = barra < 0 || ultimo.Substring(0, barra) == "1";
            foreach (var nome in ultimo.Substring(barra + 1).Split(','))
                foreach (var acao in AcoesDe(nome, ih.inputActions)) daMosca.Add(acao);
        }
        else if (Time.unscaledTime - teclasEm > SOLTAR_S)
        {
            daMosca.Clear();
            moscaNoControle = false;
        }
        if (ih != null && ih.inputActions != null && Time.unscaledTime < cimaAte) daMosca.Add(ih.inputActions.up);
    }

    void VoltarParaALuta(GameManager gm, HeroController hc)
    {
        if (gm == null || hc == null) return;
        var agora = Time.unscaledTime;
        if (lutaEmCurso && BossSceneController.IsBossScene) entrouNaLuta = true;
        if (lutaEmCurso && entrouNaLuta && !BossSceneController.IsBossScene && gm.sceneName == "GG_Workshop")
        {
            lutaEmCurso = entrouNaLuta = false;
            morreuNaLuta = true;  // perdendo ou vencendo, volta para a luta
            if (!venceuLuta) derrotas++;
        }
        if (repetindo && agora > repetirAte) repetindo = false;  // a tela não abriu: desiste
        if (!morreuNaLuta || gm.sceneName != "GG_Workshop" || hc.cState.dead || !hc.acceptingInput)
        {
            voltouEm = -1f;
            return;
        }
        if (voltouEm < 0) voltouEm = agora;
        if (agora - voltouEm < ESPERA_VOLTA_S) return;  // acordando na frente da estátua
        morreuNaLuta = false;
        voltouEm = -1f;
        if (!moscaNoControle) return;  // você desligou a mosca: fica onde está
        repetindo = true;
        repetirAte = agora + DESISTE_S;
        cimaAte = agora + CIMA_S;
        Logger.LogInfo($"Mosca jogadora: de volta à luta de {estatuaEscolhida} (nível {nivelEscolhido + 1})");
    }

    static string Acoes()
    {
        var ih = InputHandler.Instance;
        if (ih == null || ih.inputActions == null) return "";
        var nomes = new System.Collections.Generic.List<string>();
        foreach (var (nome, acao) in ACOES)
        {
            var a = acao(ih.inputActions);
            if (a != null && a.IsPressed && !nomes.Contains(nome)) nomes.Add(nome);
        }
        return string.Join(",", nomes.ConvertAll(n => "\"" + n + "\""));
    }

    void Update()
    {
        // a InControl para de ler as teclas fora de foco se isto estiver ligado
        InControl.InputManager.SuspendInBackground = false;
        LerTeclasDaMosca();
        VoltarParaALuta(GameManager.instance, HeroController.instance);
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
        Plugin.morreuNaLuta = Plugin.entrouNaLuta = Plugin.venceuLuta = false;
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
        if (!Plugin.repetindo || bossStatue == null || bossStatue.hasNoTiers) return;
        Plugin.repetindo = false;
        if (bossStatue.gameObject.name != Plugin.estatuaEscolhida || Plugin.nivelEscolhido < 0) return;
        __instance.StartCoroutine(Entrar(__instance, Plugin.nivelEscolhido));
    }

    static System.Collections.IEnumerator Entrar(BossChallengeUI ui, int nivel)
    {
        yield return new WaitForSeconds(0.6f);  // a tela termina de abrir
        if (ui != null && ui.gameObject.activeInHierarchy) ui.LoadBoss(nivel);
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
