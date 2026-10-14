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
