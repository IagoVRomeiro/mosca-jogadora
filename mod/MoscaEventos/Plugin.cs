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
    const int PORTA = 47123;
    UdpClient udp;
    float proximo;

    void Awake()
    {
        udp = new UdpClient();
        udp.Connect("127.0.0.1", PORTA);
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
    };

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
