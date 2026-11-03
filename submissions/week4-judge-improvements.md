# Week 4 — Calibratge del jutge i correcció de l'agent

Sessió del **3 de novembre de 2026**. L'agent manté `reference_date=2026-10-16` per reproduir les consultes; no és la data d'execució. Tant l'agent com el jutge s'han executat amb `gpt-4o-mini`.

## Evidències originals

L'[informe original](week4-llm-judge-evidence.md) es conserva sense canvis. SHA-256 verificat abans i després del treball:

```text
26eec5352f783c16954de5dbd6b3f354f54cd55f3e3f54856cc0309f9f5bde39
```

## Pas 1 — Comprovar el jutge amb respostes fixes

S'han creat sis exemples a `tests/fixtures/judge_zero_removals.json`, amb respostes i traces fixes i etiquetes humanes per a C1/C2/C3. Les etiquetes no s'envien al jutge. No es crida l'agent en aquestes proves.

| Exemple | C1: eina/filtres | C2: registres existents | C3: taxes/percentatges |
|---|---|---|---|
| Resposta correcta sense percentatges | PASS | PASS | PASS |
| Resposta correcta amb percentatges indefinits | PASS | PASS | PASS |
| Resposta històrica que nega registres existents | PASS | FAIL | PASS |
| Resposta amb percentatge numèric `0%` | PASS | PASS | FAIL |
| Resposta amb taxa de defectuositat inventada | PASS | PASS | FAIL |
| Crida amb data final incorrecta | FAIL | PASS | PASS |

Cada exemple es repeteix dues vegades. Un test de calibratge passa si el jutge coincideix amb les etiquetes humanes, inclosos els `FAIL` esperats.

### Primera comprovació

Es va aclarir el criteri condicional de percentatges i es va separar la resposta en text de la traça JSON. Encara s'avaluaven tots tres criteris en una única crida. Resultat: **6 tests aprovats i 6 fallits**. El jutge continuava barrejant els errors de criteris diferents.

[Log complet de la primera comprovació](week4-judge-improvements/calibration-initial.txt).

### Revisió del jutge

- Cada criteri s'avalua en una crida separada, amb la mateixa resposta i traça.
- La justificació precedeix el booleà en l'esquema de sortida.
- Les instruccions limiten cada veredicte al requisit avaluat.
- C2 explicita que reconèixer els registres és suficient; no obliga a discutir la cobertura i avalua els percentatges separadament.
- C3 explicita que ometre els percentatges és vàlid i que zero plaques és una quantitat absoluta.
- `evaluate_criteria` retorna els veredictes per comparar-los amb les etiquetes; `assert_criteria` continua fallant si qualsevol criteri de l'agent és rebutjat.

**Resultat final: 12/12 tests aprovats i 36/36 veredictes coincidents amb les etiquetes humanes.** Aquesta comprovació final fa 36 crides al jutge.

[Log complet del calibratge final](week4-judge-improvements/calibration-final.txt).

Els criteris exactes es comparteixen a `tests/judge_criteria.py` i es preserven també a la [configuració final](week4-judge-improvements/configuration.json).

## Pas 2 — Corregir les instruccions de l'agent

Només després del calibratge s'han modificat les instruccions de l'agent i la descripció de l'eina Pareto. Les funcions de dades i els càlculs no s'han canviat.

| Evidència de l'eina | Instrucció |
|---|---|
| `items` no buit, `total_quantity=0` | Hi ha registres de defecte amb zero retirades; conservar codis i zeros. |
| `items=[]` | Consultar el resum amb els mateixos filtres abans de respondre. |
| Pareto buit i `totals.control_count>0` | Hi ha controls sense files de defecte. |
| `totals.control_count=0` | Sense controls coincidents; cobertura desconeguda. |
| Percentatges `null` | Són indefinits; ometre'ls o mostrar-los com a no definits, mai com a `0%`. |

La manca del camp `control_count` no s'interpreta com a zero. S'ha afegit una comprovació final de coherència a les instruccions, sense canviar el format públic del resultat ni afegir-hi un camp estructurat `checks`.

### Iteracions

1. La primera revisió va superar el cas de registres existents amb zero retirades, però encara ometia el resum en els dos casos de Pareto buit: **1 aprovat i 2 fallits**. [Log](week4-judge-improvements/agent-first-instructions.txt).
2. Es va reforçar l'obligació de consultar el resum al principi del prompt i a la descripció de l'eina. Resultat: **2 aprovats i 1 fallit**. El tercer era un fals negatiu del test: rebutjava «No hi ha registres de defecte» tot i que la resposta reconeixia un control sense defectes. [Log](week4-judge-improvements/agent-before-test-adjustment.txt).
3. Es va ajustar l'asserció del control sa perquè permeti negar les files de defecte, però continuï rebutjant negar els controls o afirmar cobertura desconeguda. L'asserció del cas de registres de defecte existents amb zero retirades es manté estricta.

## Validació final

| Comprovació | Resultat observat |
|---|---|
| Tests sense integració | **32 aprovats**; 27 casos d'integració exclosos |
| Tres casos de zero/absència amb l'agent real | **3 aprovats**; 11 altres casos del fitxer exclosos |
| Test complet agent + jutge, repetició 1 | **1 aprovat** |
| Test complet agent + jutge, repetició 2 | **1 aprovat** |
| Test complet agent + jutge, repetició 3 | **1 aprovat** |

Logs complets: [tres casos](week4-judge-improvements/agent-final-three-cases.txt), [repetició 1](week4-judge-improvements/agent-judge-run1.txt), [repetició 2](week4-judge-improvements/agent-judge-run2.txt), [repetició 3](week4-judge-improvements/agent-judge-run3.txt).

Cada repetició és una consulta independent, sense memòria compartida. Cada test complet fa les crides de l'agent i tres crides al jutge, una per criteri.

## Reproducció

Des de l'arrel del projecte:

```sh
# Sis exemples fixos, dues vegades cadascun: 36 crides al jutge.
uv run pytest tests/test_judge_calibration.py -v -s

# Tres casos amb l'agent real.
uv run pytest tests/test_agent.py -k 'empty_pareto or zero_removals' -v -s

# Test complet amb l'agent i el jutge, una execució.
uv run pytest tests/test_judge.py -v -s

# Tests sense API.
uv run pytest -m 'not integration' -q
```

Les proves d'integració requereixen `OPENAI_API_KEY` i consumeixen API. `OPENAI_MODEL` i `OPENAI_JUDGE_MODEL` configuren els models per separat; no s'han canviat per aconseguir aquests resultats.

La [configuració preservada](week4-judge-improvements/configuration.json) inclou les instruccions de l'agent, les descripcions i esquemes de les eines, les instruccions del jutge i els criteris finals.

## Límits de la conclusió

El calibratge utilitza un conjunt petit emprat durant l'ajust, no una mostra independent per mesurar precisió general. Les millores s'han provat conjuntament; no se'n pot atribuir l'efecte a un únic canvi aïllat.

Les execucions mostren que la correcció ha funcionat en els casos comprovats. No garanteixen consistència futura ni validen tots els escenaris de l'agent: no s'ha tornat a executar la bateria completa de consultes d'integració. El calibratge amb etiquetes humanes segueix el principi de la [documentació oficial d'OpenAI sobre avaluació](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
