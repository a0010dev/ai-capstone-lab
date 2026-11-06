# Capstone: prototip sintètic de reporting

El projecte vol respondre preguntes de negoci en llenguatge natural mitjançant
un agent de reporting de només lectura. L'agent triarà eines de domini
deterministes; aquestes determinaran els fets sobre les dades operatives.

Aquest prototip implementa `get_defect_summary`, `get_defect_detail` i
`get_defect_pareto` amb la biblioteca estàndard. Aquest repositori requereix
Python 3.13 o superior. La limitació de Python 2.7 correspon a l'entorn ERP
extern i no és un requisit d'execució ni de proves d'aquest capstone.
Segueix la ubicació de reporting del repositori, `est_prog`.
Les eines són prototips funcionals de la interfície, no regles ERP definitives.
No importen `kfl_prog`, no connecten amb producció i no modifiquen dades.

La capa de dades consulta quantitats estructurades mitjançant eines, sense RAG,
LLM, framework d'agents, cerca vectorial ni generació SQL. La capa Python 3
`agent.py`, afegida a la setmana 3, connecta les tres eines amb el model; vegeu
[04-reporting-agent.ipynb](../../notebooks/04-reporting-agent.ipynb).

## Dades i contracte provisional

[synthetic_defects.json](../../data/synthetic_defects.json) conté 258 controls
ficticis, 434 línies de defectes, 130 jobs, dues seccions (TE i TV) i cinc codis
(A–E). Cobreix del **2024-01-01 al 2026-11-06**, amb registres en cadascun dels
35 mesos. Els identificadors `DEMO-*` són inventats. Les dades són fixes;
no hi ha dades reals, valors aleatoris en carregar-les ni dates relatives.

L'ampliació aporta quatre controls mensuals per secció (dies 1, 10, 20 i últim
dia de mes), inclòs el 29 de febrer de 2024. El novembre de 2026 és parcial,
amb controls els dies 1 i 6. Hi ha 37 controls sense defectes, línies totalment
reparades i casos amb diverses línies i retirades. Els sis controls originals
d'agost, setembre i octubre de 2026 es conserven sense afegir-ne en aquests tres
mesos per mantenir els casos de referència: TE sense controls a l'agost i amb
zero retirades a l'octubre. La presència d'un mes no implica cobertura completa.
L'ordre del JSON conserva primer els sis controls originals i després els nous,
ordenats per any, mes, secció i dia; no és un ordre cronològic global.

```python
from est_prog.capstone_reporting import load_defects, filter_defects

dataset = load_defects()
records = filter_defects(dataset, section='TE',
                         date_from='2026-09-01', date_to='2026-09-30')
```

La capa de recuperació carrega el JSON de `data/` a l’arrel del repositori (o una ruta explícita) i
retorna controls en l'ordre original, amb totes les línies de defectes.
No modifica les dades ni calcula mètriques. El notebook `03-defect-retrieval.ipynb`
demostra aquesta capa sense RAG ni LLM.

```python
from est_prog.capstone_reporting import (
    get_defect_summary, get_defect_detail, get_defect_pareto)

filters = dict(section='TE', date_from='2026-09-01', date_to='2026-09-30')
summary = get_defect_summary(**filters)
pareto = get_defect_pareto(metric='removed_boards', **filters)
detail = get_defect_detail(**filters)
```

Els filtres són opcionals. Les dates són cadenes ISO `YYYY-MM-DD`, amb límits
inclusius sobre la data fictícia del control. La secció es compara exactament;
una secció sense coincidències retorna zero controls. Filtres invàlids generen
`ValueError`. Cada resposta inclou filtres, origen sintètic, versió del contracte
i un avís estructurat sobre la semàntica provisional.

El detall conserva controls sense defectes i agrupa les línies originals sota
el control corresponent. El nombre de controls i la mostra es compten una sola
vegada per control. Errors, afectades, reparades i retirades se sumen per separat
des de les línies. Les quantitats de plaques són ocurrències registrades, no
plaques físiques úniques; tampoc la mostra és un cens de plaques úniques. Aquestes
sumes il·lustren la reconciliació del fixture, no defineixen regles de fabricació.
No s'exposa cap taxa ni es resten reparacions/retirades de les plaques afectades.

La consulta TE de setembre retorna 3 controls, mostra 220, errors 23,
afectades 19, reparades 4 i retirades 12. Les retirades s'expliquen amb
`DEMO-DEF-001` (3), `DEMO-DEF-002` (1) i `DEMO-DEF-004` (8).
L'estabilitat dels resultats depèn de la mateixa versió del fixture; no hi ha
un mecanisme de captures de dades vives en aquest prototip.

## Pareto de defectes

`get_defect_pareto(section=None, date_from=None, date_to=None,
metric='removed_boards')` agrupa les línies originals per `defect_code`.
Admet `errors`, `affected_boards`, `repaired_boards` i `removed_boards`;
qualsevol altra mètrica genera `ValueError`. Comparteix els filtres del resum
i del detall, sense canviar-ne els contractes.

La resposta afegeix `metric`, `total_quantity` i `items`. Cada element conté
`defect_code`, `quantity`, `percentage`, `cumulative_percentage` i `records`.
Cada referència de `records` conserva `job_id`, `control_id`, `record_id` i la
quantitat de la mètrica: permet localitzar la línia a `get_defect_detail` amb
els mateixos filtres i justificar cada grup. Inclou també línies de valor zero.

L'ordre és quantitat descendent i, en cas d'empat, codi ascendent. El percentatge
és `100 * quantity / total_quantity`: contribució al total de la mètrica
seleccionada, **no una taxa de defectuositat**. L'acumulat es calcula des de les
quantitats acumulades, sense sumar percentatges arrodonits. La tool retorna
percentatges sense arrodoniment de presentació. Amb total zero, els percentatges
són `null` i es conserven els codis observats; sense línies de defecte, `items`
és buit i el total és zero.

Per TE al setembre, les retirades són C: 8 (66,67%), A: 3 (25%) i B: 1 (8,33%),
amb percentatges acumulats 66,67%, 91,67% i 100% (arrodonits aquí per llegibilitat).
El total 12 coincideix amb el resum i el detall. Els codis identifiquen defectes
registrats; el Pareto no demostra les causes del problema.

## Executar la demostració i les proves

Des de l'arrel del repositori (la demo només necessita la biblioteca estàndard):

```sh
python3 -m est_prog.capstone_reporting
uv run pytest -m "not integration" -q
```

La demo imprimeix el resum, el Pareto, els jobs/controls/línies i `3 + 1 + 8 = 12`.
Les proves de recuperació comproven càrrega, filtres opcionals i combinats,
controls sans, dates límit, seleccions buides, validació, rutes explícites i
lectures independents. Les proves de Pareto reconcilien les quatre mètriques
amb resum i detall; cobreixen referències, percentatges, empats, totals zero
i determinisme sense mutació compartida.

## Connexió amb l'agent (setmana 3)

> "Show me the defect summary for section TE this month and show me the jobs
> that explain the removals."

`agent.py` interpreta la pregunta, resol el període i pot cridar les tres eines
amb els mateixos filtres. El detall permet explicar quins registres i jobs
contribueixen a les retirades. Si es demana un rànquing per codi, consulta el
Pareto amb la mètrica triada
(`removed_boards` per defecte). Els totals i percentatges es calculen a les eines;
l’agent no atribueix causes de negoci a partir del rànquing.
El notebook 04 mostra crides, respostes i comprovacions d’onze casos de negoci, inclosos els de Pareto.

El backend sintètic se substituirà per l'ERP/API, mantenint les signatures
públiques i l'estructura de resposta sempre que sigui possible. Aquesta
substitució requerirà validar regles, unitats, cobertura i consistència de les
dades reals; no es reutilitzaran automàticament les convencions del fixture.
La consulta agregada específica de jobs afectats queda fora d'aquest increment.

## Migració asíncrona

`agent.run_agent` és una coroutine: cal executar-la amb `await`.
PydanticAI gestiona les crides a eines i la validació dels arguments. Els notebooks poden usar `await run_agent(...)` directament;
des d'un script síncron es pot usar `asyncio.run(run_agent(...))`.

El mòdul `tools.py` proporciona les signatures asíncrones de les tres eines.
Actualment executa el backend JSON en un fil amb `asyncio.to_thread`, sense
bloquejar el bucle d'events. Aquest límit permet substituir les lectures per
crides HTTP asíncrones quan es disposi del contracte de l'API real. No s'ha
implementat cap connexió real en aquest increment.

Les funcions de `defects.py` i les exportacions de l'arrel del paquet continuen
sent síncrones per a càlculs i consultes deterministes locals. La demostració
`python -m est_prog.capstone_reporting` les continua executant sense model.

## Streaming

`await run_agent(pregunta, on_event=callback)` activa el streaming. El callback
ha de ser asíncron i rep diccionaris `round_start`, `text_delta`, `tool_start`,
`tool_end` i `completed`. El valor retornat continua contenint `answer`,
`tool_calls`, `model` i `reference_date`. Sense callback, l'agent usa la via
de resposta completa per mantenir els consumidors i el jutge existents.

Streamlit mostra el text progressivament i la traça de cada eina quan s'executa.
Els arguments han d'estar complets abans d'executar cap eina. El text provisional
d'una ronda amb eines es reemplaça a la ronda següent; si hi ha un error a mig
flux, no es desa com una resposta completada. La traça disponible i l'error
continuen visibles després dels reruns de la interfície.

## Context de conversa

`run_agent` accepta `message_history` i retorna aquest mateix camp ampliat amb
el torn actual. Per continuar una conversa, passa `resultat["message_history"]`
a la crida següent. L'historial inclou les preguntes, les respostes i les crides
i resultats de les eines; es copia i no es modifica el que proporciona el caller.
Sense historial, la consulta continua començant una conversa nova.

Streamlit conserva aquest context dins la sessió i el buida amb «Esborra la
conversa». Això permet completar un aclariment amb «te» sense repetir les dates.
L'historial no és una font per inventar producció: `sample_quantity` és mostra
inspeccionada i `errors` són ocurrències d'error. Per a plaques afectades cal usar
`affected_boards`, també com a ocurrències registrades, no com a plaques úniques.

## Runtime PydanticAI

`agent.py` conté l'única implementació de l'agent. PydanticAI genera els esquemes
amb les eines tipades i gestiona els reintents, el cicle model/eines, els límits
de peticions, l'historial i la instrumentació. El context asíncron de l'agent
obre i tanca els recursos del proveïdor. No cal seleccionar cap backend.

Les instruccions compartides són a `instructions.py`. L'adaptador d'aplicació
manté els esdeveniments de Streamlit i els costos acumulats per sessió. El jutge
també usa PydanticAI amb sortida tipada. Les proves locals injecten `FunctionModel`
amb les peticions externes desactivades, mantenint les eines reals del fixture.
