# Guía de estudio: logging estructurado

## Objetivo

Esta guía explica la capa de logging estructurado del repositorio y cómo defender sus decisiones técnicas. El objetivo no es memorizar líneas de código, sino comprender:

- qué problema resuelve;
- qué diferencia existe entre log, auditoría y dato clínico;
- cómo se correlacionan operaciones;
- cómo se mide una etapa;
- cómo se evita exponer información sensible;
- qué límites siguen pendientes.

## 1. El problema anterior

El hito de auditoría ya permitía responder:

```text
¿Qué estado durable tiene el run?
¿Cuántos intentos de carga existieron?
¿La carga terminó o falló?
¿Qué SQLSTATE produjo el fallo?
```

Sin embargo, no permitía observar con suficiente detalle:

```text
¿Cuánto duró la validación?
¿Qué componente estaba ejecutándose?
¿La demora ocurrió en raw capture, validación, persistencia o exportación?
¿Qué operaciones pertenecieron al mismo comando?
¿Qué ocurrió antes de que el estado durable cambiara?
```

La auditoría registra hechos de negocio operativo que deben sobrevivir. El logging registra telemetría para diagnóstico durante la ejecución.

## 2. Tres capas diferentes

### Datos clínicos

Representan pacientes, encuentros, diagnósticos, observaciones, medicamentos y procedimientos.

No deben aparecer en los logs como filas o valores individuales.

### Auditoría durable

Se almacena en PostgreSQL:

```text
audit.pipeline_runs
audit.pipeline_run_events
```

Es la fuente de verdad para estados, intentos y fallos de ejecución.

### Logging estructurado

Se emite por `stderr` como JSON o texto estructurado.

Sirve para:

```text
diagnóstico
búsqueda
agregación
medición de duración
correlación entre componentes
integración futura con herramientas de observabilidad
```

No es durable por sí mismo. Si el entorno no recoge `stderr`, el log se pierde.

## 3. Por qué JSON

Un mensaje tradicional puede verse así:

```text
Validation completed for patients in 4 ms
```

Un parser tendría que adivinar dónde están el dataset y la duración.

El mismo evento estructurado es:

```json
{
  "event": "pipeline.validation.completed",
  "dataset": "patients",
  "duration_ms": 4,
  "outcome": "success"
}
```

Cada atributo tiene nombre, tipo y semántica. Esto permite filtrar sin interpretar lenguaje natural.

## 4. Esquema mínimo

Todos los eventos JSON incluyen:

```text
schema_version
timestamp
level
event
component
message
```

El esquema se versiona como:

```text
1.0.0
```

La versión es importante porque otros sistemas pueden depender de nombres y tipos de campos. Cambiar `duration_ms` por `elapsed` sin versionar rompería consultas y dashboards.

## 5. Evento frente a mensaje

Ejemplo:

```text
event   = pipeline.validation.completed
message = Completed validate_records_against_contract.
```

`event` es un contrato estable para máquinas.

`message` está dirigido a humanos y puede mejorar su redacción sin cambiar la identidad operacional.

Una regla práctica:

```text
filtrar y agregar por event
leer message para entender rápidamente el evento
```

## 6. Componentes

Los loggers están organizados bajo:

```text
clinical_data_platform.<component>
```

Componentes actuales:

```text
cli
pipeline
database
cohort
demo
```

El formatter elimina el prefijo y produce:

```json
{"component":"pipeline"}
```

Esto permite comparar, por ejemplo, errores de `database` frente a errores de `pipeline`.

## 7. Correlation ID

El `correlation_id` agrupa todas las operaciones de una invocación.

Un comando `run-demo` puede producir:

```text
correlation_id C1
    ├── run de patients R1
    ├── run de encounters R2
    ├── run de diagnoses R3
    ├── run de observations R4
    ├── run de medications R5
    ├── run de procedures R6
    └── cohort run H1
```

C1 no reemplaza R1–R6 ni H1.

### Diferencias

| Identificador | Alcance |
|---|---|
| `correlation_id` | una invocación o flujo observacional |
| `run_id` | una validación y persistencia de dataset |
| `attempt_number` | un intento de carga del mismo run |
| `cohort_run_id` | una derivación analítica |

## 8. Context propagation

El módulo usa `contextvars`.

Sin esta técnica habría que modificar muchas firmas:

```python
validate_dataset(..., correlation_id, run_id, dataset)
persist_dataset(..., correlation_id, run_id, dataset)
build_cohort(..., correlation_id)
```

Con contexto propagado:

```python
with bind_log_context(run_id=run_id, dataset=dataset):
    operation_a()
    operation_b()
```

Los logs internos heredan los campos sin convertirlos en parámetros funcionales del dominio.

Al salir del `with`, el contexto anterior se restaura. Esto evita que un dataset herede accidentalmente el `run_id` de otro.

## 9. Operaciones medidas

`log_operation` rodea una unidad de trabajo:

```python
with log_operation(
    logger,
    "pipeline.validation",
    operation="validate_records_against_contract",
    stage="validation",
) as completed:
    result = validate()
    completed["rows_valid"] = len(result.valid_records)
```

Produce:

```text
pipeline.validation.started
pipeline.validation.completed
```

El evento final incluye:

```text
outcome = success
duration_ms
rows_valid
```

Si ocurre una excepción:

```text
pipeline.validation.started
pipeline.validation.failed
```

La excepción se vuelve a lanzar. El logging no altera la semántica del programa.

## 10. Por qué medir con `perf_counter`

`time.perf_counter()` es apropiado para duraciones porque es monotónico.

El reloj de calendario puede cambiar por:

```text
sincronización NTP
cambio manual
ajustes del sistema
```

El timestamp se obtiene del reloj de calendario para indicar cuándo ocurrió el evento. La duración se calcula con reloj monotónico.

## 11. Niveles

El repositorio acepta:

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

Uso actual:

| Nivel | Uso |
|---|---|
| `INFO` | inicio y éxito de operaciones normales |
| `ERROR` | operación fallida que se propaga |
| `CRITICAL` | fallo secundario grave, como no poder persistir la auditoría del fallo |

No conviene usar `ERROR` para una fila inválida esperada por contrato. Esa fila forma parte del resultado de calidad, no necesariamente de un fallo operacional.

## 12. Logs de pipeline

Una ejecución válida produce eventos como:

```text
pipeline.run.started
pipeline.raw_capture.started
pipeline.raw_capture.completed
pipeline.validation.started
pipeline.validation.completed
pipeline.output_write.started
pipeline.output_write.completed
pipeline.quality_report.started
pipeline.quality_report.completed
pipeline.run.validated
```

Los counts son agregados:

```text
rows_received
rows_valid
rows_invalid
validation_errors
```

No se registran:

```text
patient_id
valor de una observación
código individual rechazado
fila CSV completa
```

## 13. Logs de persistencia

Etapas principales:

```text
persistence.preflight
persistence.audit_registration
persistence.transaction
```

### Preflight

Verifica outputs, contratos, raw lineage y journal.

### Audit registration

Registra el run validado e inicia el intento de carga.

### Transaction

Carga filas clínicas, errores de validación y transición `completed`.

Si la transacción clínica falla:

```text
persistence.transaction.failed
persistence.failure_audited
```

Si además falla la escritura del estado durable:

```text
persistence.failure_audit_failed
level = critical
```

## 14. Idempotencia observable

Cuando un run ya está completado:

```text
persistence.run.idempotent
already_loaded = true
```

No se presenta como un segundo éxito de escritura. El evento comunica que la operación fue reconocida y omitida de manera segura.

## 15. Errores normalizados

Campos:

```text
error_type
error_message
error_code
```

Ejemplo:

```text
error_type = psycopg.errors.ForeignKeyViolation
error_code = 23503
```

`error_code` usa SQLSTATE cuando existe. Es más estable que comparar textos completos del error.

## 16. Por qué no se registra el traceback completo

Un traceback puede contener:

```text
rutas locales
nombres de archivos
fragmentos de SQL
parámetros
credenciales
valores de registros
```

La implementación conserva clase, mensaje sanitizado y SQLSTATE. Un entorno controlado podría añadir trazas seguras en el futuro, pero no deben activarse sin revisar exposición y acceso.

## 17. Redacción

Campos sensibles conocidos se sustituyen por:

```text
<redacted>
```

Ejemplos:

```text
patient_id
database_url
password
rejected_value
record
```

El texto libre también elimina:

```text
credenciales en URLs
Key (...)=(...)
líneas DETAIL de PostgreSQL
```

### Limitación esencial

Ningún redactor es perfecto.

La defensa principal es no pasar valores clínicos al logger. La redacción es una segunda barrera.

## 18. stdout frente a stderr

El CLI mantiene:

```text
stdout → resultado solicitado por el usuario o script
stderr → telemetría y diagnósticos
```

Esto permite:

```bash
clinical-data validate-contracts > resultado.txt 2> logs.jsonl
```

Un pipeline puede consumir `resultado.txt` sin mezclarlo con logs.

## 19. Formato text

JSON es el formato predeterminado.

Para lectura manual:

```powershell
$env:CLINICAL_DATA_LOG_FORMAT = "text"
```

Ambos formatos utilizan los mismos campos semánticos. `text` cambia la representación, no el modelo del evento.

## 20. Consultas con jq

Fallos:

```bash
jq 'select(.outcome == "failure")' logs.jsonl
```

Un run:

```bash
jq 'select(.run_id == "<run-id>")' logs.jsonl
```

Operaciones lentas:

```bash
jq 'select((.duration_ms // 0) > 500)' logs.jsonl
```

Errores por SQLSTATE:

```bash
jq -s 'group_by(.error_code) |
       map({error_code: .[0].error_code, count: length})' logs.jsonl
```

## 21. Qué no debe afirmarse

No es correcto decir:

```text
Los logs son una auditoría inmutable.
El sistema tiene trazabilidad distribuida completa.
La plataforma es PHI-ready.
Existe monitorización productiva.
Hay alertas y dashboards.
```

Sí es correcto decir:

```text
La aplicación emite eventos estructurados y correlacionados.
Las operaciones principales tienen duración y resultado.
Existe redacción defensiva y minimización de datos.
El estado durable sigue en PostgreSQL.
El formato está preparado para transporte futuro.
```

## 22. Ejercicios

### Ejercicio 1

Ejecuta el demo con JSON y redirige stderr:

```powershell
$env:CLINICAL_DATA_LOG_FORMAT = "json"
clinical-data run-demo --repository-root . 2> logs.jsonl
```

Identifica:

```text
un correlation_id
seis run_id
un cohort_run_id
```

### Ejercicio 2

Calcula cuál etapa fue más lenta usando `duration_ms`.

### Ejercicio 3

Provoca una carga de encuentros antes de pacientes y localiza:

```text
persistence.transaction.failed
error_code = 23503
persistence.failure_audited
```

Comprueba que el valor del paciente no aparece.

### Ejercicio 4

Cambia temporalmente el formato a `text` y compara la semántica de los campos.

### Ejercicio 5

Añade un componente de prueba con `get_logger("example")` y una operación medida. No pases valores de filas.

## 23. Preguntas de entrevista

1. ¿Por qué logging y auditoría no son equivalentes?
2. ¿Qué problema resuelve un correlation ID?
3. ¿Por qué el run ID no reemplaza al correlation ID?
4. ¿Por qué se usa `contextvars`?
5. ¿Qué diferencia existe entre timestamp y duration?
6. ¿Por qué SQLSTATE es útil?
7. ¿Por qué los logs van a stderr?
8. ¿Por qué no se incluyen tracebacks completos?
9. ¿Qué limitaciones tiene la redacción automática?
10. ¿Cómo demostrarías que un fallo clínico sigue siendo auditable aunque el log se pierda?

## 24. Respuesta profesional

> Implementé una capa de logging estructurado separada de la auditoría durable. El CLI genera un correlation ID y el contexto se propaga mediante contextvars hacia pipeline, persistencia, demo y cohortes. Cada operación importante emite eventos started, completed o failed con duración, etapa y resultado. Los errores conservan tipo y SQLSTATE, mientras que credenciales, identificadores clínicos y detalles de claves se redactan. Los logs se escriben a stderr y no contienen filas clínicas. PostgreSQL sigue siendo la fuente de verdad para estados e intentos; los logs son telemetría operacional y pueden enviarse a infraestructura externa en una etapa posterior.

## 25. Límites actuales

Pendiente:

```text
transporte centralizado
OpenTelemetry
traces distribuidos
métricas
dashboards
alertas
retención administrada
rotación automática
controles productivos para PHI
```

El hito demuestra una base de observabilidad defendible, no una plataforma de monitorización productiva completa.
