# Guía de estudio: carga masiva con PostgreSQL COPY

## 1. Objetivo del hito

El objetivo no era cambiar una palabra en el código y afirmar que la plataforma es más rápida. El objetivo técnico fue reemplazar la persistencia fila por fila por una ruta de carga masiva real, manteniendo intactas las garantías clínicas y de auditoría ya construidas.

La propiedad central es:

```text
mayor eficiencia de transferencia
sin sacrificar
contratos, terminología, historial, inmutabilidad, transacciones ni auditoría
```

El resultado usa:

```text
COPY FROM STDIN
→ staging temporal tipado
→ INSERT ... SELECT ... ON CONFLICT
→ tablas clínicas gobernadas
```

## 2. Qué problema tenía `executemany`

Antes, la persistencia seguía conceptualmente esta ruta:

```text
CSV validado
→ lista completa de diccionarios
→ lista completa de tuplas convertidas
→ executemany
→ muchos INSERT parametrizados
```

Esto era funcional para los fixtures pequeños, pero tenía dos problemas de escalabilidad.

### 2.1 Memoria

El mismo dataset quedaba representado varias veces:

```text
archivo CSV
lista de diccionarios
lista de tuplas convertidas
buffers del driver
```

La memoria podía crecer aproximadamente con el número de filas del lote.

### 2.2 Comunicación con PostgreSQL

`executemany` sigue una estrategia orientada a filas. Aunque el driver pueda optimizar internamente parte del trabajo, no equivale a usar el protocolo de carga masiva de PostgreSQL.

`COPY` está diseñado específicamente para transferir muchas filas a PostgreSQL con menos overhead por registro.

## 3. Qué es COPY

`COPY` es una operación nativa de PostgreSQL para mover datos entre una tabla y un flujo de datos.

En esta plataforma se utiliza:

```sql
COPY tabla (columna_1, columna_2, ...)
FROM STDIN;
```

`STDIN` significa que el cliente envía el contenido por la conexión. La aplicación no necesita crear un archivo dentro del servidor PostgreSQL ni conceder al servidor acceso al sistema de archivos local.

Con psycopg, el patrón conceptual es:

```python
with cursor.copy(statement) as copy:
    for row in rows:
        copy.write_row(row)
```

Cada fila se convierte y transmite conforme se itera.

## 4. Por qué COPY directo no era suficiente

Podría parecer que la solución más simple sería:

```sql
COPY clinical.patients (...) FROM STDIN;
```

Pero COPY directo no resuelve la política de reconciliación de la plataforma.

### Pacientes

Los pacientes representan un snapshot actual. Una nueva versión puede:

- insertar un paciente nuevo;
- actualizar el snapshot existente;
- crear una nueva versión SCD Type 2 solo cuando cambia el contenido clínico.

### Eventos

Los encuentros, diagnósticos, observaciones, medicamentos y procedimientos son eventos inmutables. El sistema debe:

- aceptar un identificador nuevo;
- tolerar una repetición exacta;
- rechazar el mismo identificador con contenido clínico diferente.

Estas reglas dependen de:

```text
ON CONFLICT
triggers
hashes clínicos
foreign keys
terminología
```

COPY por sí solo no ofrece un `ON CONFLICT` equivalente. Por eso se utiliza staging.

## 5. Patrón COPY + staging + merge

La arquitectura separa dos responsabilidades.

### Transferencia

```text
Python
→ COPY
→ tabla temporal
```

### Reconciliación

```text
tabla temporal
→ INSERT ... SELECT
→ ON CONFLICT
→ tabla clínica
```

La sentencia conceptual es:

```sql
INSERT INTO clinical.patients (
    patient_id,
    sex_at_birth,
    birth_date,
    death_date,
    source_system,
    source_run_id,
    source_sha256
)
SELECT
    patient_id,
    sex_at_birth,
    birth_date,
    death_date,
    source_system,
    source_run_id,
    source_sha256
FROM staging
ON CONFLICT (patient_id)
DO UPDATE SET
    sex_at_birth = EXCLUDED.sex_at_birth,
    ...;
```

Esta sentencia es set-based: PostgreSQL procesa el conjunto completo recibido en staging.

## 6. Tabla temporal de staging

La tabla se crea con un nombre único:

```text
_cdp_<dataset>_<sufijo_aleatorio>
```

Ejemplo conceptual:

```text
_cdp_observations_8ab27c104af1
```

Se crea mediante:

```sql
CREATE TEMP TABLE staging ON COMMIT DROP AS
SELECT columnas_de_carga
FROM clinical.tabla_objetivo
WITH NO DATA;
```

### Qué copia esta técnica

Copia los tipos de las columnas seleccionadas.

### Qué no copia

No copia automáticamente:

```text
primary keys
foreign keys
check constraints
indexes
triggers
defaults
```

Eso es intencional. Staging sirve para recibir y tipar el lote, no para representar el modelo clínico definitivo.

### `ON COMMIT DROP`

Cuando la transacción termina, PostgreSQL elimina la tabla temporal. No queda una tabla de staging permanente que deba limpiarse manualmente.

## 7. Por qué los triggers siguen funcionando

COPY escribe en staging, pero el merge escribe en la tabla clínica real.

Por lo tanto, al ejecutar:

```sql
INSERT INTO clinical.<entidad>
SELECT ... FROM staging
```

PostgreSQL activa los triggers normales de la tabla objetivo.

### Pacientes

```text
trg_patients_set_record_hash
→ calcula record_sha256

trg_patients_capture_history
→ mantiene clinical.patient_history
```

### Diagnósticos, observaciones, medicamentos y procedimientos

```text
trigger de terminología
→ asigna normalized_concept_id

trigger de inmutabilidad
→ calcula hash en INSERT
→ compara hash en conflicto
```

### Resultado

La optimización no evita las reglas clínicas. Solo mejora la forma en que el lote llega al punto donde esas reglas se ejecutan.

## 8. Qué habría sido un atajo incorrecto

Varias alternativas habrían aumentado velocidad a costa de romper garantías.

### Desactivar triggers

```sql
SET session_replication_role = replica;
```

Esto podría saltarse historial, terminología e inmutabilidad. No se utiliza.

### COPY directo a tablas internas

Copiar manualmente a `clinical.patient_history` habría duplicado la lógica SCD2 y creado riesgo de inconsistencias. No se utiliza.

### Eliminar constraints durante la carga

Quitar foreign keys o checks permitiría datos imposibles y complicaría la recuperación. No se utiliza.

### Cargar y validar después

La plataforma conserva el orden:

```text
validación contractual
→ persistencia
```

No introduce datos no validados en el modelo clínico con la esperanza de corregirlos posteriormente.

## 9. Lectura streaming de los CSV validados

La persistencia ahora utiliza dos funciones nuevas.

### `inspect_csv_records`

Recorre el archivo para:

```text
validar el header
rechazar columnas duplicadas o vacías
rechazar filas con más valores que columnas
contar registros
```

Retiene solo el estado necesario para la inspección.

### `iter_csv_records`

Reabre el archivo y entrega una fila a la vez:

```text
fila CSV
→ diccionario normalizado
→ conversión de tipos
→ copy.write_row
```

La persistencia ya no crea una lista completa de tuplas antes de comenzar la transferencia.

## 10. Límite real de memoria

Es importante describir el alcance con precisión.

### Mejorado

La fase:

```text
outputs validados
→ PostgreSQL
```

ahora puede trabajar con memoria acotada por fila y buffers internos, en lugar de construir un batch completo de Python.

### Todavía pendiente

La fase de validación contractual actual todavía lee el dataset completo en una lista:

```text
fuente raw
→ read_csv_records
→ validación contractual
```

Por tanto, no sería correcto afirmar que todo el pipeline es streaming. El hito optimiza específicamente la persistencia.

## 11. Conversión de tipos

Los CSV internos contienen texto. Antes de COPY, cada row builder transforma los campos al tipo Python apropiado.

Ejemplos:

```text
birth_date
string ISO → datetime.date

start_datetime
string ISO → datetime.datetime

value_numeric
string → float

run_id
UUID existente → uuid.UUID

campo opcional vacío
"" → None
```

Psycopg adapta estos objetos al tipo PostgreSQL de la tabla temporal.

## 12. Plan declarativo por dataset

Cada entidad tiene un `CopyMergePlan` que declara:

```text
schema objetivo
tabla objetivo
columnas en orden
columnas de conflicto
columnas actualizables
política loaded_at
```

Esto evita construir un bloque condicional enorme en `database.py`.

La separación es:

```text
bulk.py
→ algoritmo genérico COPY + merge

registry.py
→ configuración específica de cada entidad

database.py
→ transacción, auditoría y orquestación
```

## 13. Seguridad de identificadores SQL

Los nombres de schemas, tablas y columnas no se interpolan como texto libre.

Se construyen mediante:

```python
psycopg.sql.Identifier(...)
```

Esto distingue correctamente entre:

```text
valor SQL
identificador SQL
fragmento SQL estructural
```

Los planes provienen del registro interno, no de argumentos arbitrarios del usuario.

## 14. Validación antes de cargar

La preflight comprueba:

```text
quality_report.json
header exacto de valid_<dataset>.csv
header exacto de invalid_<dataset>.csv
header exacto de validation_errors.csv
conteos de filas
contrato y hash
raw receipt y hash
execution journal y hash chain
UUID y fechas
```

No basta con que el archivo “parezca CSV”. Debe coincidir con la evidencia de la ejecución validada.

## 15. Verificación durante COPY

Después de transmitir el archivo, la aplicación compara:

```text
filas contadas en preflight
vs
filas escritas mediante COPY
```

Una diferencia produce error y rollback.

Esto protege frente a una modificación del archivo entre la inspección y la carga. No es una protección contra todos los escenarios de concurrencia del sistema de archivos, pero evita aceptar silenciosamente un lote diferente.

## 16. Topología transaccional

La arquitectura de auditoría previa se conserva.

### Transacción A

```text
registrar run validado
importar journal local
crear evento loading
incrementar attempt_number
COMMIT
```

### Transacción B

```text
crear staging temporal
COPY registros clínicos
merge hacia tabla clínica
COPY errores de validación
crear evento completed
actualizar proyección del run
COMMIT
```

### Transacción C, solo ante fallo

```text
crear evento failed
registrar tipo, mensaje y SQLSTATE
registrar detalles agregados
COMMIT
```

La separación permite que el fallo sobreviva al rollback de la carga clínica.

## 17. Fallo durante COPY

Supongamos que una fila contiene una representación que PostgreSQL no puede adaptar.

Resultado:

```text
COPY falla
→ transacción B aborta
→ staging desaparece al terminar la transacción
→ no quedan filas clínicas parciales
→ transacción C registra failed
```

## 18. Fallo durante el merge

Ejemplo: un encuentro referencia un paciente inexistente.

```text
COPY a staging
→ puede completarse

INSERT ... SELECT hacia clinical.encounters
→ foreign key failure 23503

transacción B
→ rollback completo

transacción C
→ fallo durable
```

Staging no convierte datos inválidos relacionalmente en datos válidos. Las foreign keys siguen aplicándose en el target.

## 19. Conflictos de eventos inmutables

### Repetición exacta

Mismo identificador y mismo contenido clínico:

```text
ON CONFLICT DO UPDATE
→ trigger calcula hash esperado
→ coincide con OLD.record_sha256
→ trigger retorna OLD
```

El evento original y su lineage no se reemplazan.

### Conflicto real

Mismo identificador y contenido diferente:

```text
trigger calcula hash esperado
→ no coincide
→ RAISE EXCEPTION SQLSTATE 23514
→ rollback
→ run failed auditado
```

COPY no cambia la política de inmutabilidad.

## 20. Historial de pacientes

El merge de pacientes activa el trigger SCD2.

### Paciente nuevo

```text
INSERT snapshot
→ INSERT versión current en patient_history
```

### Mismo contenido

```text
UPDATE operativo
→ record_sha256 no cambia
→ no se crea versión clínica falsa
```

### Contenido clínico diferente

```text
cerrar versión current anterior
crear nueva versión current
vincular cambio al nuevo source_run_id
```

## 21. Errores de validación

Los errores se cargan con COPY directo a:

```text
audit.validation_errors
```

No necesitan staging + merge porque:

- pertenecen a un `run_id` concreto;
- un run completado no vuelve a cargar;
- forman parte de la misma transacción que la carga clínica.

Si el COPY de errores falla, también se revierten las filas clínicas del intento.

## 22. Idempotencia

La idempotencia principal sigue siendo por run.

```text
run status = completed
→ begin_loading_attempt informa already_completed
→ no COPY
→ no staging
→ no nuevas filas
```

No se confía únicamente en `ON CONFLICT` para evitar una segunda carga. El estado durable del run detiene el trabajo antes de persistir.

## 23. Reintentos

Un run fallido conserva:

```text
mismo run_id
nuevo attempt_number
misma evidencia validada
nueva tabla staging temporal
nuevo evento loading
```

La nueva tabla tiene un nombre único para evitar colisiones con otras sesiones o intentos.

## 24. Logging estructurado

La ruta COPY añade eventos operacionales:

```text
persistence.copy.started
persistence.copy.completed
persistence.copy.failed

persistence.validation_error_copy.started
persistence.validation_error_copy.completed
persistence.validation_error_copy.failed
```

Campos útiles:

```text
loading_method
rows_copied
rows_merged
validation_errors_copied
staging_table
duration_ms
attempt_number
```

Estos logs son telemetría, no auditoría durable.

## 25. `rows_copied` y `rows_merged`

No representan exactamente lo mismo.

### `rows_copied`

Número de filas transferidas a staging.

Responde:

```text
¿Cuántas filas del output validado llegaron al flujo bulk de PostgreSQL?
```

### `rows_merged`

Número de filas reportadas por el `INSERT ... SELECT ... ON CONFLICT`.

Responde:

```text
¿Cuántas filas procesó la reconciliación del target?
```

El número de registros persistidos del run continúa basándose en las filas validadas transferidas.

## 26. Por qué no existe V009

No se añadió ninguna estructura persistente.

```text
staging
→ TEMP
→ session-local
→ ON COMMIT DROP
```

No cambian:

```text
tablas permanentes
funciones
triggers
constraints
indexes
views
```

Por eso la secuencia de migraciones sigue en V008.

## 27. Qué prueba el CI

La suite valida:

```text
planes COPY válidos e inválidos
inspección streaming de CSV
COPY hacia staging
merge set-based
actualización por conflicto
COPY directo de errores
seis entidades clínicas
terminología
historial SCD2
inmutabilidad
foreign keys
rollback
reintentos
idempotencia
Docker
```

El resultado de este hito fue:

```text
82 pruebas superadas
Ruff superado
mypy estricto superado
PostgreSQL integration superado
Docker y smoke tests superados
```

## 28. Qué no demuestra todavía

El hito prueba corrección funcional, no rendimiento cuantificado.

Todavía no responde:

```text
¿Cuántas filas por segundo carga?
¿Cuánto mejora frente a executemany?
¿Cuál es el peak de memoria?
¿Cómo escala de 1 000 a 1 000 000 de filas?
¿Qué entidad es el cuello de botella?
¿Cuánto tiempo consume COPY y cuánto el merge con triggers?
```

Estas preguntas pertenecen al benchmark documentado.

## 29. Diferencia entre implementación y benchmark

### Implementación COPY

Demuestra:

```text
la ruta existe
usa el protocolo COPY
conserva las garantías
pasa pruebas
```

### Benchmark

Debe demostrar con mediciones:

```text
hardware y software conocidos
poblaciones reproducibles
warm-up
repeticiones
mediana y dispersión
tiempo por etapa
filas por segundo
memoria
comparación justa con baseline
```

No se deben mezclar ambos hitos para evitar una afirmación de rendimiento sin evidencia.

## 30. Archivos para estudiar

Orden recomendado:

```text
1. src/clinical_data_platform/bulk.py
2. src/clinical_data_platform/ingestion.py
3. src/clinical_data_platform/registry.py
4. src/clinical_data_platform/database.py
5. tests/test_bulk_loading.py
6. tests/test_analysis_workflow.py
7. migrations V005, V006 y V007
```

## 31. Preguntas de comprensión

1. ¿Por qué COPY directo al target no sustituye el patrón staging + merge?
2. ¿Qué diferencia existe entre transferencia y reconciliación?
3. ¿Por qué la tabla staging no necesita foreign keys?
4. ¿Dónde se ejecutan realmente los triggers clínicos?
5. ¿Qué ocurre si el merge viola una foreign key?
6. ¿Por qué el estado `loading` debe estar comprometido antes del COPY?
7. ¿Por qué los errores de validación se cargan en la misma transacción clínica?
8. ¿Qué diferencia existe entre idempotencia por run e idempotencia por primary key?
9. ¿Qué parte del pipeline sigue materializando el dataset completo?
10. ¿Por qué este hito no demuestra todavía una mejora de velocidad?

## 32. Ejercicios prácticos

### Ejercicio 1: observar eventos COPY

Ejecuta el demo capturando logs:

```powershell
$env:CLINICAL_DATA_LOG_FORMAT = "json"
clinical-data run-demo --repository-root . 2> data/copy-loading.jsonl
```

Busca:

```powershell
Select-String -Path data/copy-loading.jsonl -Pattern 'persistence.copy'
```

Comprueba que aparecen eventos started y completed.

### Ejercicio 2: verificar ausencia de staging permanente

Después de cargar, ejecuta:

```sql
SELECT schemaname, tablename
FROM pg_catalog.pg_tables
WHERE tablename LIKE '_cdp_%';
```

Esperado después del commit:

```text
0 filas
```

### Ejercicio 3: confirmar historial

Carga una versión nueva de un paciente con un cambio clínico y consulta:

```sql
SELECT
    patient_id,
    record_sha256,
    valid_from_run_id,
    valid_to_run_id,
    is_current
FROM clinical.patient_history
WHERE patient_id = '<id>'
ORDER BY patient_version_id;
```

Debe existir una versión cerrada y una actual.

### Ejercicio 4: provocar conflicto inmutable

Reutiliza un `observation_id` con un valor diferente en un nuevo run validado.

Comprueba:

```text
clinical.observations no cambia
run termina failed
SQLSTATE = 23514
evento failed permanece en audit.pipeline_run_events
```

### Ejercicio 5: explicar el límite de memoria

Describe por separado:

```text
memoria durante validación
memoria durante persistencia
```

No uses la frase “el pipeline completo es streaming”, porque no sería exacta.

## 33. Explicación para una entrevista

> La plataforma usa PostgreSQL COPY FROM STDIN para transmitir registros validados a tablas temporales tipadas con memoria acotada durante la persistencia. No copia directamente a las tablas clínicas porque necesitamos reconciliación ON CONFLICT. Después de COPY ejecutamos un INSERT SELECT set-based hacia el target, de modo que siguen activos los triggers de terminología, hashes, historial SCD2 e inmutabilidad. La carga clínica, los errores de validación y el evento completed comparten una transacción; si COPY o el merge fallan, todo se revierte y una transacción separada conserva el fallo durable. El hito demuestra corrección de la ruta bulk, mientras que la mejora cuantitativa se medirá en un benchmark separado.

## 34. Explicación breve

> COPY acelera la transferencia hacia PostgreSQL, staging permite aplicar ON CONFLICT, y el merge sobre las tablas clínicas conserva todos los triggers y constraints.

## 35. Límites honestos

```text
COPY de filas tipadas, no COPY binario
validación aún no streaming
sin benchmark cuantitativo todavía
sin orquestación paralela
sin controles para PHI
sin afirmación de producción clínica
```

Estos límites no invalidan el hito. Definen exactamente qué se implementó y qué queda pendiente.
