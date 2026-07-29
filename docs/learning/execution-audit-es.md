# Guía de estudio: estados completos y fallos auditados

## Objetivo

Este hito corrige una limitación importante del diseño anterior: `audit.pipeline_runs` se insertaba dentro de la misma transacción que los datos clínicos. Cuando la carga fallaba, PostgreSQL revertía correctamente los datos parciales, pero también eliminaba el registro que explicaba el fallo.

El nuevo diseño garantiza simultáneamente:

```text
ningún dato clínico parcial
+ evidencia durable del intento fallido
```

## 1. El problema transaccional

Imagina una carga de diagnósticos:

```text
INSERT pipeline_run
INSERT diagnosis D001
INSERT diagnosis D002
INSERT diagnosis D003 → falla
```

Si todo ocurre en una sola transacción:

```text
ROLLBACK
→ desaparecen D001 y D002
→ desaparece también pipeline_run
```

La primera parte es correcta. La segunda reduce la auditabilidad: después del fallo no queda una fila durable con etapa, excepción o momento del intento.

No se resuelve haciendo `COMMIT` de cada fila clínica. Eso permitiría cargas parciales y sería peor.

La solución consiste en separar la transacción de auditoría de la transacción clínica.

## 2. Máquina de estados

Ruta normal:

```text
created
→ raw_captured
→ validating
→ validated
→ loading
→ completed
```

Ruta con fallo de persistencia:

```text
created
→ raw_captured
→ validating
→ validated
→ loading
→ failed
```

Ruta con reintento:

```text
...
→ loading       intento 1
→ failed        intento 1
→ loading       intento 2
→ completed     intento 2
```

### Significado de cada estado

| Estado | Significado |
|---|---|
| `created` | se asignó identidad a la ejecución |
| `raw_captured` | los bytes fuente ya están en la landing zone |
| `validating` | se ejecuta el contrato |
| `validated` | existen outputs verificables; aún no se han cargado |
| `loading` | un intento posee la carga PostgreSQL |
| `completed` | datos y estado terminal se confirmaron juntos |
| `failed` | el intento terminó con error auditado |

`completed` es terminal. `failed` puede reabrirse únicamente hacia `loading` mediante un nuevo intento.

## 3. Por qué el quality report ya no dice completed

Antes, al terminar la validación, el reporte usaba:

```text
status = completed
```

Eso era ambiguo. Solo se había completado la validación, no la carga a PostgreSQL.

Ahora utiliza:

```text
status = validated
```

La ejecución solo se convierte en `completed` después de que:

```text
filas clínicas
+ errores de validación
+ evento de finalización
+ proyección actual del run
```

se confirman en una misma transacción.

## 4. Journal local

La validación puede fallar antes de tener conexión a PostgreSQL. Por eso se crea un journal local:

```text
data/processed/<dataset>/execution/<run-id>.jsonl
```

JSONL significa que cada línea es un objeto JSON independiente.

Ejemplo conceptual:

```json
{"sequence_number":1,"to_status":"created",...}
{"sequence_number":2,"to_status":"raw_captured",...}
{"sequence_number":3,"to_status":"validating",...}
{"sequence_number":4,"to_status":"validated",...}
```

Si no existe el archivo fuente:

```json
{"sequence_number":1,"to_status":"created",...}
{"sequence_number":2,"to_status":"failed","stage":"raw_capture",...}
```

Así también quedan registrados fallos anteriores a PostgreSQL.

## 5. Cadena de hashes

Cada evento tiene:

```text
previous_event_sha256
event_sha256
```

El primer evento no tiene hash anterior. Los posteriores apuntan al evento previo:

```text
Evento 1 hash A
Evento 2 previous=A, hash B
Evento 3 previous=B, hash C
Evento 4 previous=C, hash D
```

Cambiar el contenido del evento 2 altera su hash. Aunque un atacante dejara el hash anterior escrito, el verificador detectaría que el contenido ya no produce ese SHA-256. Si recalculara el hash 2, se rompería la referencia desde el evento 3.

Esto proporciona evidencia de manipulación. No impide físicamente que alguien con permisos administrativos reescriba todos los eventos y todos los hashes.

## 6. Qué se incluye en el hash

El hash se calcula sobre JSON canónico con:

```text
journal_version
run_id
dataset
sequence_number
attempt_number
from_status
to_status
stage
occurred_at
previous_event_sha256
error_type
error_message
error_code
details
```

No incluye `event_sha256`, porque un hash no puede depender circularmente de sí mismo.

JSON canónico significa:

```text
claves ordenadas
separadores constantes
UTF-8
sin formato visual variable
```

Sin canonicalización, dos representaciones equivalentes podrían generar hashes diferentes por espacios u orden de claves.

## 7. Importación a PostgreSQL

Cuando la validación terminó, la plataforma verifica:

```text
quality report
contrato
raw receipt
raw object
outputs CSV
journal local
cadena de hashes
```

Luego importa el journal a:

```text
audit.pipeline_run_events
```

y crea la proyección actual en:

```text
audit.pipeline_runs
```

La diferencia es:

```text
pipeline_runs       → estado actual resumido
pipeline_run_events → historial ordenado completo
```

Esta separación se parece al patrón event log + current projection, aunque el repositorio no implementa event sourcing general.

## 8. Las tres transacciones

### Transacción 1: identidad y adquisición

Se confirma:

```text
run validado
+ journal importado
+ estado loading
+ intento incrementado
```

Al terminar esta transacción, ya existe evidencia durable de que comenzó una carga.

### Transacción 2: datos clínicos

Se intenta confirmar:

```text
filas clínicas
+ validation_errors
+ evento completed
+ estado completed
```

Si una sola operación falla, todo se revierte.

### Transacción 3: fallo

Después del rollback clínico se confirma:

```text
evento failed
+ estado failed
+ tipo de excepción
+ mensaje
+ SQLSTATE
+ detalles
+ timestamp
```

La excepción original vuelve al llamador. La plataforma no convierte un fallo real en un resultado exitoso solo porque pudo auditarlo.

## 9. SQLSTATE

PostgreSQL utiliza códigos SQLSTATE de cinco caracteres.

Ejemplos relevantes:

```text
23503 → foreign_key_violation
23514 → check_violation
```

En el repositorio, un encuentro cargado antes de sus pacientes puede fallar con `23503`. Un código terminológico rechazado por una función o constraint puede producir `23514`.

El código facilita agrupación técnica de fallos sin depender únicamente del texto del mensaje.

## 10. Reintentos

Un reintento conserva el mismo:

```text
run_id
source_sha256
contract_sha256
journal local
outputs validados
```

Solo aumenta:

```text
attempt_count
```

y añade nuevos eventos.

Ejemplo:

```text
seq 1 created       attempt 0
seq 2 raw_captured  attempt 0
seq 3 validating    attempt 0
seq 4 validated     attempt 0
seq 5 loading       attempt 1
seq 6 failed        attempt 1
seq 7 loading       attempt 2
seq 8 completed     attempt 2
```

El fallo anterior no se elimina. Los campos de fallo de `pipeline_runs` se limpian porque la proyección actual ya es `completed`, pero el evento 6 permanece.

## 11. Idempotencia versus reintento

No son lo mismo.

### Idempotencia después de completed

```text
misma llamada
mismo run_id
estado completed
→ no escribir de nuevo
→ already_loaded = True
```

### Reintento después de failed

```text
misma validación
mismo run_id
estado failed
→ nuevo loading attempt
→ volver a ejecutar la transacción clínica
```

El sistema debe diferenciar ambos casos para no bloquear recuperaciones ni duplicar cargas ya completadas.

## 12. Campos principales de pipeline_runs

### Identidad y lineage

```text
run_id
dataset_name
source_sha256
contract_sha256
raw_receipt_id
```

### Estado actual

```text
status
current_stage
attempt_count
```

### Tiempos

```text
started_at
validated_at
loading_started_at
completed_at
failed_at
updated_at
```

### Fallo actual

```text
failure_stage
failure_type
failure_message
failure_code
failure_details
```

### Integridad del journal

```text
local_journal_event_count
local_journal_head_sha256
audit_event_count
audit_head_sha256
```

### Historia incompleta anterior

```text
audit_gap_reason
```

## 13. Por qué hay dos heads

`local_journal_head_sha256` identifica el último evento producido durante la validación local.

`audit_head_sha256` identifica el último evento durable total, incluyendo loading, failed, retries y completed.

En una ejecución completada sin reintentos:

```text
local journal: 4 eventos, head del validated
durable audit: 6 eventos, head del completed
```

El head local demuestra que los primeros cuatro eventos importados son exactamente los que estaban vinculados al quality report.

## 14. Runs anteriores a V008

No existe evidencia suficiente para reconstruir todos sus estados intermedios. El sistema no inventa eventos.

Se registra:

```text
audit_gap_reason = pre_v008_execution_history_unavailable
```

Esto permite distinguir:

```text
historial completo validado
versus
estado legado conocido pero sin timeline completo
```

## 15. Consultas que debes dominar

### Estado actual

```sql
SELECT
    run_id,
    dataset_name,
    status,
    current_stage,
    attempt_count,
    failure_code,
    failure_message
FROM audit.pipeline_runs
ORDER BY updated_at DESC;
```

### Timeline

```sql
SELECT
    sequence_number,
    attempt_number,
    from_status,
    to_status,
    stage,
    occurred_at,
    error_code,
    error_message
FROM audit.pipeline_run_events
WHERE run_id = '<uuid>'
ORDER BY sequence_number;
```

### Runs fallidos

```sql
SELECT
    dataset_name,
    COUNT(*) AS failures
FROM audit.pipeline_runs
WHERE status = 'failed'
GROUP BY dataset_name
ORDER BY failures DESC;
```

### Runs reintentados

```sql
SELECT
    run_id,
    dataset_name,
    status,
    attempt_count
FROM audit.pipeline_runs
WHERE attempt_count > 1;
```

## 16. Código que debes recorrer

Orden recomendado:

```text
execution.py
→ pipeline.py
→ V008 migration
→ run_audit.py
→ database.py
→ test_pipeline.py
→ test_run_audit.py
→ tests de conflictos
```

Responsabilidades:

| Archivo | Responsabilidad |
|---|---|
| `execution.py` | estados, eventos, hashes y journal local |
| `pipeline.py` | emitir eventos de validación |
| `V008` | estructura y restricciones PostgreSQL |
| `run_audit.py` | registrar, transicionar, fallar, reintentar y verificar |
| `database.py` | coordinar las tres transacciones |

## 17. Preguntas que debes poder responder

1. ¿Por qué el fallo desaparecía antes de V008?
2. ¿Por qué no basta con insertar el run dentro de la transacción clínica?
3. ¿Por qué tampoco conviene confirmar cada fila clínica individualmente?
4. ¿Qué diferencia hay entre `validated` y `completed`?
5. ¿Por qué existe un journal local antes de PostgreSQL?
6. ¿Qué detecta una cadena SHA-256 y qué no puede impedir?
7. ¿Por qué existen `local_journal_head_sha256` y `audit_head_sha256`?
8. ¿Qué se confirma en cada una de las tres transacciones?
9. ¿Qué diferencia existe entre idempotencia y reintento?
10. ¿Por qué los runs anteriores a V008 reciben un audit gap en vez de eventos reconstruidos?

## 18. Ejercicios

### Ejercicio 1: fallo por dependencia

Valida encuentros antes de cargar pacientes.

Resultado esperado:

```text
clinical.encounters = 0
pipeline run = failed
failure_code = 23503
attempt_count = 1
```

Carga pacientes y repite la misma carga de encuentros.

Resultado esperado:

```text
clinical.encounters = 7
pipeline run = completed
attempt_count = 2
timeline = 8 eventos
```

### Ejercicio 2: journal manipulado

Modifica `stage` en la segunda línea del journal sin recalcular hashes.

La carga debe detenerse antes de registrar el run en PostgreSQL.

### Ejercicio 3: evento durable manipulado

Después de una carga exitosa, cambia un `event_sha256` en PostgreSQL.

Ejecuta:

```python
validate_pipeline_run_audit(connection, run_id)
```

Debe detectar una cadena inválida.

### Ejercicio 4: transición ilegal

Intenta cambiar directamente:

```text
completed → loading
```

El trigger debe rechazarlo. Un run completado no puede reabrirse accidentalmente.

### Ejercicio 5: consulta operacional

Construye una consulta que muestre:

```text
dataset
runs totales
runs fallidos
runs reintentados
promedio de intentos
```

## 19. Explicación profesional

> Implementé una máquina de estados explícita para ejecuciones clínicas y separé la auditoría durable de la transacción de datos. La validación produce primero un journal JSONL append-only con una cadena SHA-256. Al cargar, ese journal se verifica e importa a PostgreSQL. El estado loading se confirma antes de escribir datos clínicos; después, datos y completed se confirman juntos. Cuando la carga falla, los datos se revierten y una transacción posterior conserva failed, el SQLSTATE y la excepción. El mismo run puede reintentarse sin eliminar el historial del intento anterior.

## 20. Límite actual

Esta solución no reemplaza logging estructurado. Un audit event responde:

```text
qué estado cambió
cuándo
para qué run
con qué error terminal
```

Un log estructurado responde además:

```text
qué operaciones internas ocurrieron
qué duración tuvo cada paso
qué componente emitió el mensaje
qué contexto técnico acompañó la operación
```

El logging estructurado permanece como el siguiente hito independiente.
