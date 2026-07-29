# Guía de estudio: historial clínico y política snapshot

## Propósito

Esta guía explica por qué la plataforma no utiliza el mismo comportamiento de actualización para todas las entidades clínicas.

Debes poder responder:

- qué diferencia existe entre una dimensión mutable y un evento clínico;
- por qué `patients` conserva un snapshot actual y un historial SCD tipo 2;
- por qué encuentros, diagnósticos y observaciones son append-only;
- qué identifica `record_sha256`;
- qué ocurre cuando llega un duplicado exacto;
- qué ocurre cuando se reutiliza un identificador con contenido diferente;
- por qué la landing zone raw no sustituye al historial de registros transformados.

## 1. Problema anterior

Antes de V005, las cuatro tablas clínicas utilizaban `INSERT ... ON CONFLICT DO UPDATE`.

Conceptualmente:

```text
mismo identificador
    → reemplazar columnas
    → actualizar source_run_id
    → perder el estado anterior
```

Esto era suficiente para demostrar una carga transaccional, pero no definía una semántica histórica.

El problema no es técnico solamente. También es clínico:

```text
¿Un patient_id representa una entidad cuyo estado cambia?
¿Un observation_id representa una medición que debe sobrescribirse?
```

La respuesta no es la misma.

## 2. Política híbrida

La plataforma adopta:

```text
patients
    → snapshot actual + SCD Type 2

encounters
 diagnoses
 observations
    → eventos inmutables
```

La política está declarada en:

```text
src/clinical_data_platform/history.py
```

Y se aplica físicamente mediante:

```text
V005__add_clinical_history_policy.sql
```

## 3. Qué es un snapshot

Un snapshot representa el estado conocido de una entidad en un momento determinado.

Ejemplo:

```text
P001
sex_at_birth = F
birth_date = 1985-04-12
death_date = NULL
```

`clinical.patients` contiene únicamente el estado actual aceptado.

Si una carga posterior añade una fecha de fallecimiento, el estado actual cambia. Sin historial, el estado anterior desaparecería.

## 4. Qué es SCD Type 2

SCD significa Slowly Changing Dimension.

En una estrategia tipo 2, cada cambio de negocio genera una versión nueva.

Ejemplo:

| patient_id | death_date | valid_from | valid_to | is_current |
|---|---|---|---|---|
| P001 | NULL | t1 | t2 | false |
| P001 | 2026-01-03 | t2 | NULL | true |

La tabla:

```text
clinical.patient_history
```

conserva:

```text
patient_version_id
patient_id
atributos demográficos
record_sha256
valid_from_run_id
valid_to_run_id
source_sha256
valid_from
valid_to
is_current
```

## 5. Por qué pacientes usa SCD2

Los datos demográficos pueden cambiar o completarse:

- fecha de fallecimiento;
- clasificación demográfica corregida;
- sistema fuente;
- otros atributos futuros.

El consumidor analítico suele necesitar dos vistas:

```text
¿Cuál es el estado actual?
¿Cuál era el estado conocido antes de una determinada carga?
```

Por eso se mantienen:

```text
clinical.patients
clinical.patient_history
```

## 6. Por qué los eventos son append-only

Un encuentro, diagnóstico u observación representa un hecho clínico identificado por un ID de origen.

Ejemplo:

```text
observation_id = O001
value_numeric = 146
unit = mmHg
```

Si después llega:

```text
observation_id = O001
value_numeric = 120
```

no es seguro interpretar automáticamente que la medición anterior debe reemplazarse.

Podría ser:

- una corrección válida;
- una colisión de identificadores;
- un error de extracción;
- una medición distinta con un ID reutilizado;
- un cambio retroactivo no autorizado.

La plataforma elige una regla conservadora:

```text
mismo ID + mismo contenido
    → duplicado exacto, no-op

mismo ID + contenido diferente
    → conflicto, rollback
```

## 7. Hash de registro

Cada tabla clínica contiene:

```text
record_sha256
```

Este hash se calcula sobre el contenido de negocio normalizado.

No incluye:

```text
source_run_id
source_sha256
loaded_at
```

porque esos campos describen lineage, no el significado clínico del registro.

### Distinción de hashes

```text
source_sha256
    → archivo raw completo

raw_manifest_sha256
    → receipt de recepción

contract_sha256
    → contrato ejecutado

record_sha256
    → contenido normalizado de una fila clínica
```

## 8. Flujo de pacientes

### Inserción nueva

```text
INSERT clinical.patients
    ↓
trigger calcula record_sha256
    ↓
se inserta snapshot actual
    ↓
trigger crea versión current en patient_history
```

### Duplicado exacto

```text
UPSERT patient_id existente
    ↓
record_sha256 no cambia
    ↓
se actualiza lineage del snapshot actual
    ↓
no se crea versión histórica
```

### Cambio de negocio

```text
UPSERT patient_id existente
    ↓
record_sha256 cambia
    ↓
se cierra la versión current anterior
    ↓
se inserta una nueva versión current
```

## 9. Flujo de eventos

### Evento nuevo

```text
INSERT
    ↓
trigger calcula record_sha256
    ↓
se conserva evento y lineage original
```

### Duplicado exacto

```text
ON CONFLICT DO UPDATE
    ↓
trigger compara hash
    ↓
hash igual
    ↓
RETURN OLD
```

`RETURN OLD` impide que el duplicado reemplace el evento o su lineage original.

### Conflicto

```text
mismo ID
+ hash distinto
    ↓
RAISE EXCEPTION
    ↓
rollback del dataset load
```

También se revierte la fila de `audit.pipeline_runs` insertada dentro de esa misma transacción.

## 10. Por qué el raw no resuelve esto

La landing zone raw conserva archivos fuente exactos.

Pero no responde directamente:

```text
¿Qué versión normalizada de P001 estaba activa?
¿Qué carga cerró esa versión?
¿Qué evento fue aceptado como el original?
```

Raw history y transformed-record history son capas distintas:

```text
raw
    → evidencia de entrada

clinical current/history
    → semántica normalizada
```

## 11. Consultas de estudio

### Estado actual

```sql
SELECT
    patient_id,
    sex_at_birth,
    birth_date,
    death_date,
    record_sha256,
    source_run_id
FROM clinical.patients
ORDER BY patient_id;
```

### Historial

```sql
SELECT
    patient_id,
    sex_at_birth,
    death_date,
    valid_from_run_id,
    valid_to_run_id,
    valid_from,
    valid_to,
    is_current
FROM clinical.patient_history
ORDER BY patient_id, patient_version_id;
```

### Invariante de una versión actual

```sql
SELECT patient_id, COUNT(*)
FROM clinical.patient_history
WHERE is_current
GROUP BY patient_id
HAVING COUNT(*) <> 1;
```

El resultado esperado es cero filas.

### Eventos y hashes

```sql
SELECT
    observation_id,
    patient_id,
    observation_code,
    value_numeric,
    unit,
    record_sha256,
    source_run_id
FROM clinical.observations
ORDER BY observation_id;
```

## 12. Pruebas importantes

Lee:

```text
tests/test_history.py
```

### Prueba de pacientes

Verifica:

1. primera carga crea cinco versiones current;
2. recargar datos idénticos no crea versiones nuevas;
3. cambiar P001 crea una segunda versión;
4. la versión anterior queda cerrada;
5. `valid_to_run_id` identifica la carga que produjo el cambio.

### Prueba de eventos

Verifica:

1. un evento se inserta;
2. un duplicado exacto conserva el lineage original;
3. reutilizar el mismo ID con contenido distinto genera error;
4. la transacción completa se revierte.

## 13. Ejercicios personales

### Ejercicio 1: cambio demográfico

Modifica una copia de `patients.csv` para añadir o cambiar un atributo válido de P001.

Ejecuta:

```powershell
clinical-data validate-dataset patients <archivo> `
  --raw-root data/raw `
  --output-dir data/processed/patients-change `
  --reference-date 2026-07-29

clinical-data load-dataset patients `
  --raw-root data/raw `
  --output-dir data/processed/patients-change
```

Explica las dos filas de `clinical.patient_history`.

### Ejercicio 2: duplicado exacto

Carga dos veces un archivo de encuentros idéntico, generando dos validation runs distintos.

Comprueba que:

```text
source_run_id del evento no cambia
record_sha256 no cambia
ambos pipeline runs existen
```

Explica por qué la recepción se audita aunque el evento no se reescriba.

### Ejercicio 3: conflicto

Cambia `encounter_type` conservando el mismo `encounter_id`.

Comprueba que:

```text
la validación estructural puede pasar
la persistencia rechaza el conflicto
el pipeline run no queda persistido
el evento original no cambia
```

### Ejercicio 4: diseñar tombstones

Propón cómo representarías que un sistema fuente retire un diagnóstico.

No basta con `DELETE`. Debes considerar:

```text
correction_id
supersedes_id
status
recorded_at
source_run_id
```

No implementes la solución hasta definir su semántica.

## 14. Preguntas de entrevista

### ¿Por qué no usar SCD2 para todo?

Porque un evento clínico no es necesariamente una dimensión mutable. Versionar automáticamente una observación con el mismo ID podría legitimar una colisión o corrección no modelada.

### ¿Por qué conservar una tabla current además del historial?

Porque las consultas operacionales y muchas cohortes requieren el estado actual sin tener que filtrar `is_current` en cada acceso. El historial mantiene auditabilidad.

### ¿Por qué excluir lineage del record hash?

Porque una segunda recepción del mismo contenido tiene lineage diferente pero significado clínico igual. Incluir lineage generaría versiones falsas.

### ¿Es bitemporal?

No. La implementación conserva tiempo de sistema de la versión (`valid_from`/`valid_to`), pero no modela por separado el período clínico efectivo comunicado por la fuente.

### ¿Puede un administrador modificar el historial?

Sí, si tiene permisos suficientes. La política está implementada mediante constraints, triggers y privilegios actuales, no mediante almacenamiento regulatorio inmutable.

## 15. Explicación profesional

> La plataforma utiliza una política histórica híbrida. `clinical.patients` mantiene el snapshot actual y un trigger SCD tipo 2 conserva cambios demográficos en `clinical.patient_history`. Los encuentros, diagnósticos y observaciones se consideran eventos inmutables: un duplicado exacto es idempotente, pero reutilizar un identificador con contenido diferente aborta la transacción. Un SHA-256 de contenido normalizado diferencia cambios clínicos de cambios de lineage.

## 16. Límites actuales

Todavía no se implementan:

- tombstones;
- mensajes formales de corrección;
- bitemporalidad completa;
- merge o split de identidades;
- supersession de eventos;
- estrategia histórica para medications y procedures;
- carga masiva mediante staging y `COPY`.

Estos límites deben permanecer explícitos.
