# Capstone: prototip sintètic de reporting

El projecte vol respondre preguntes de negoci en llenguatge natural mitjançant
un agent de reporting de només lectura. L'agent triarà eines de domini
deterministes; aquestes determinaran els fets sobre les dades operatives.

Aquest primer increment només implementa `get_defect_summary` i
`get_defect_detail` amb la biblioteca estàndard, compatibles amb Python 2.7 i 3.
Segueix la ubicació de reporting del repositori, `est_prog`.
Les eines són prototips funcionals de la interfície, no regles ERP definitives.
No importen `kfl_prog`, no connecten amb producció i no modifiquen dades.

No s'utilitza RAG: aquest exercici consulta quantitats estructurades mitjançant
eines, sense necessitat de recuperar documents. No incorpora un LLM, framework
d'agents, cerca vectorial ni generació SQL.

## Dades i contracte provisional

[synthetic_defects.json](../../data/synthetic_defects.json) conté sis controls
ficticis, quatre jobs, dues seccions i tres codis. Els identificadors `DEMO-*`
són inventats. No hi ha dades reals, valors aleatoris ni dates relatives.

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
from est_prog.capstone_reporting import get_defect_summary, get_defect_detail

filters = dict(section='TE', date_from='2026-09-01', date_to='2026-09-30')
summary = get_defect_summary(**filters)
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

## Executar la demostració i les proves

Des de l'arrel del repositori, sense dependències addicionals:

```sh
python2.7 -m est_prog.capstone_reporting
python3 -m unittest discover -s tests -v
```

La demo imprimeix el resum, els jobs/controls/línies i `3 + 1 + 8 = 12`.
Les proves de recuperació comproven càrrega, filtres opcionals i combinats,
controls sans, dates límit, seleccions buides, validació, rutes explícites i
lectures independents.

## Connexió futura amb l'agent

> "Show me the defect summary for section TE this month and show me the jobs
> that explain the removals."

Un agent futur interpretarà la pregunta, resoldrà el període i cridarà les dues
eines amb els mateixos filtres. Utilitzarà el detall per explicar quins jobs
contribueixen a les retirades. L'LLM no calcularà les mètriques de fabricació.

El backend sintètic se substituirà per l'ERP/API, mantenint les signatures
públiques i l'estructura de resposta sempre que sigui possible. Aquesta
substitució requerirà validar regles, unitats, cobertura i consistència de les
dades reals; no es reutilitzaran automàticament les convencions del fixture.
Pareto i consulta específica de jobs afectats queden fora d'aquest increment.
