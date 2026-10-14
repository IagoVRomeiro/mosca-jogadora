using System; using System.IO; using System.Linq; using System.Reflection;
var pasta = args[0];
var dlls = Directory.GetFiles(pasta, "*.dll");
using var ctx = new MetadataLoadContext(new PathAssemblyResolver(dlls), "mscorlib");
var asm = ctx.LoadFromAssemblyPath(Path.Combine(pasta, "Assembly-CSharp.dll"));
var f = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
foreach (var (tipo, nomes) in new[] {
    ("PlayerData", new[]{"instance","health","maxHealth","healthBlue","geo","MPCharge","TakeHealth","AddHealth","AddGeo","TakeGeo"}),
    ("HeroController", new[]{"instance","cState","TakeDamage","AddHealth","transform","rb2d","current_velocity"}),
    ("HealthManager", new[]{"Hit","Die","TakeDamage","hp","isDead"}),
    ("GameManager", new[]{"instance","sceneName","playerData","GetSceneNameString"}),
    ("HeroControllerStates", new[]{"dead","onGround","wallSliding","focusing"}),
}) {
    var t = asm.GetType(tipo);
    if (t == null) { Console.WriteLine($"{tipo}: NÃO EXISTE"); continue; }
    foreach (var n in nomes) {
        var m = t.GetMembers(f).Where(x => x.Name == n).Select(x => x is MethodInfo mi ? $"{n}({string.Join(",", mi.GetParameters().Select(p => p.ParameterType.Name))})" : x is FieldInfo fi ? $"{n}:{fi.FieldType.Name}" : x is PropertyInfo pi ? $"{n}:{pi.PropertyType.Name}" : n);
        Console.WriteLine($"{tipo}.{n}: " + (m.Any() ? string.Join(" | ", m) : "—"));
    }
}

foreach (var nome in new[]{"HeroActions", "InputHandler"}) {
    var t = asm.GetType(nome);
    if (t == null) { Console.WriteLine($"{nome}: NÃO EXISTE"); continue; }
    var membros = t.GetMembers(f).Where(x => x is FieldInfo || x is PropertyInfo).Select(x => x.Name);
    Console.WriteLine($"{nome}: " + string.Join(", ", membros));
}

{
    var t = asm.GetType("HeroActions");
    var campo = t.GetField("left", f);
    var tipo = campo.FieldType;
    Console.WriteLine($"tipo da ação: {tipo.FullName} em {tipo.Assembly.GetName().Name}");
    Console.WriteLine("IsPressed: " + string.Join(", ", tipo.GetMembers(BindingFlags.Public | BindingFlags.Instance).Where(m => m.Name is "IsPressed" or "Value" or "WasPressed").Select(m => m.Name + " (" + m.DeclaringType.Name + ")")));
}

{
    foreach (var (tipo, nomes) in new[] {
        ("PlayerData", new[]{"respawnScene", "respawnMarkerName", "respawnType"}),
        ("HeroControllerStates", new[]{"hazardDeath", "hazardRespawning", "transitioning"}),
    }) {
        var t = asm.GetType(tipo);
        foreach (var n in nomes) {
            var m = t.GetMember(n, f);
            Console.WriteLine($"campo {tipo}.{n}: " + (m.Length > 0 ? (m[0] is FieldInfo fi ? fi.FieldType.Name : "membro") : "—"));
        }
    }
}

{
    foreach (var nome in new[]{"HealthManager", "BossSceneController"}) {
        var t = asm.GetType(nome);
        if (t == null) { Console.WriteLine($"chefe? {nome}: NÃO EXISTE"); continue; }
        var membros = t.GetMembers(f).Where(x => x is FieldInfo || x is PropertyInfo || x is MethodInfo)
            .Select(x => x.Name).Where(n => n.ToLower().Contains("boss") || n.ToLower().Contains("hp") || n is "Instance" or "IsBossScene" or "bossesDeadWaitTime" or "BossHealthLookup").Distinct();
        Console.WriteLine($"chefe? {nome}: " + string.Join(", ", membros));
    }
}
