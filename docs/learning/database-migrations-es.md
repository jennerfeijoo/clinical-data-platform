# Guía de estudio: migraciones formales de PostgreSQL

## Propósito

Esta guía explica cómo la base evoluciona mediante migraciones SQL ordenadas, inmutables y auditables. Debes poder distinguir instalación, upgrade, baseline, drift y rollback operacional.

## 1. Por qué no basta un `schema.sql`

Un archivo monolítico mezcla normalmente:

- creación inicial;
- `ALTER TABLE`;
- backfills;
- índices;
- compatibilidad histórica.

Puede ser parcialmente idempotente, pero no responde con precisión:

```text
¿Qué versión tiene esta base?
¿Qué cambios se aplicaron?
¿En qué orden?
¿El SQL actual coincide con el aplicado?
¿Se probó realmente el upgrade?
```

Por eso `sql/schema.sql` fue eliminado.

## 2. Historia actual

```text
src/clinical_data_platform/migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
├── V003__add_contract_lineage.sql
└── V004__add_raw_landing_lineage.sql
```

Patrón obligatorio:

```text
VNNN__descripcion_en_snake_case.sql
```

Las versiones deben comenzar en V001 y ser contiguas.

## 3. Qué representa cada versión

### V001

Crea schemas, ejecuciones básicas, pacientes y errores.

### V002

Añade encuentros, diagnósticos, observaciones, cohortes, tabla analítica e índices longitudinales.

### V003

Añade lineage contractual:

```text
contract_path
contract_version
contract_sha256
```

### V004

Añade lineage de la landing zone raw:

```text
raw_receipt_id
raw_received_at
raw_storage_version
raw_manifest_path
raw_manifest_sha256
raw_object_path
raw_size_bytes
```

Las filas anteriores reciben marcadores explícitos `legacy/unmanaged`. No se inventan receipts históricos.

## 4. Tabla de historial

El motor utiliza:

```text
public.schema_migrations
```

Campos:

```text
version
name
checksum
applied_at
execution_ms
execution_type
application_version
```

Está en `public` porque V001 crea el schema `audit`; colocar anticipadamente el historial dentro de `audit` introduciría una dependencia circular.

## 5. Descubrimiento

`discover_migrations()`:

1. inspecciona recursos empaquetados;
2. valida nombres;
3. extrae versión y nombre;
4. calcula SHA-256;
5. ordena;
6. exige secuencia contigua;
7. rechaza nombres duplicados.

La migración es un objeto con versión, nombre, ruta, checksum y SQL.

## 6. Inmutabilidad por checksum

Al aplicar una migración, PostgreSQL almacena el SHA-256 de sus bytes exactos.

En ejecuciones posteriores:

```text
checksum empaquetado == checksum registrado
```

Si difieren, se lanza `MigrationChecksumError`.

Regla:

> Una migración aplicada no se edita. Se crea la siguiente versión.

Ahora que V004 existe, una corrección nueva sería, por ejemplo:

```text
V005__correct_raw_lineage_constraint.sql
```

No debe modificarse V004.

## 7. Transacción y advisory lock

`migrate_database()` ejecuta:

```text
advisory lock
→ detectar estructura
→ crear/leer historial
→ validar checksums
→ ejecutar SQL pendiente
→ registrar historia
→ commit
```

Si una migración falla, su DDL y su fila de historial se revierten juntos.

El advisory lock evita que dos procesos cooperantes migren simultáneamente la misma base.

## 8. Estado, migración y validación

Estado:

```powershell
clinical-data database-status
```

Migración:

```powershell
clinical-data database-migrate
```

Validación estricta:

```powershell
clinical-data database-validate
```

Conceptos:

```text
current  = última versión registrada
latest   = versión más alta empaquetada
pending  = versiones posteriores a current
detected = estructura reconocida físicamente
```

`current` y `detected` deben ser coherentes.

## 9. Instalación nueva

En una base vacía:

```text
0 → V001 → V002 → V003 → V004
```

Cada versión se registra como:

```text
execution_type = migration
```

Una segunda ejecución no repite el SQL.

## 10. Upgrade gestionado

Para probar específicamente V003 → V004:

```powershell
clinical-data database-migrate --target-version 3
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

Estado intermedio esperado:

```text
current = 3
latest = 4
pending = [4]
```

Antes de V004, `audit.pipeline_runs.raw_receipt_id` no existe. Después, deben existir los siete campos raw.

Esto prueba el camino de actualización, no solo una instalación nueva.

## 11. Baseline

Una base creada antes del historial puede contener una estructura completa conocida.

El motor no la adopta automáticamente. Tras revisión explícita:

```powershell
clinical-data database-migrate --baseline-existing
```

Las versiones equivalentes se registran como:

```text
execution_type = baseline
```

Baseline significa que la estructura ya existía y fue reconocida; no significa que el SQL histórico se ejecutó.

Los estados parciales se rechazan. Para V004, tener solo algunos campos raw es un estado parcial.

## 12. Por qué baseline debe ser explícito

Sin confirmación, una estructura modificada manualmente podría declararse falsamente equivalente a una versión oficial. La bandera obliga al operador a asumir y documentar esa decisión.

## 13. Downgrades

El motor es forward-only. No automatiza:

```text
DROP COLUMN
DROP TABLE
reversión de tipos
```

Una reversión operacional puede requerir backup/restore, despliegue compatible, migración correctiva o estrategia expand/contract.

`git revert` no revierte por sí solo el estado persistente de PostgreSQL.

## 14. Drift

### Drift de archivo

```text
checksum empaquetado != checksum registrado
```

### Drift estructural

```text
estructura detectada != versión registrada
```

Ejemplos:

- historial dice V004, pero faltan columnas raw;
- existen algunas columnas raw sin historia V004;
- se editó una migración aplicada.

El motor rechaza estos estados en lugar de repararlos silenciosamente.

## 15. Relación con contratos y raw storage

```text
contrato
    define qué fuente es válida

migración
    define cómo evoluciona PostgreSQL

raw landing
    conserva los bytes previos a interpretación
```

V004 persiste referencias al raw, pero no implementa el almacenamiento raw. Esa responsabilidad pertenece a `raw.py`.

Una migración de base no debe capturar archivos, y `raw.py` no debe alterar tablas.

## 16. Pruebas

`tests/test_migration.py` cubre:

- secuencia V001–V004;
- fresh install;
- reejecución idempotente;
- upgrade desde V001;
- upgrade V003 → V004;
- baseline explícito;
- rechazo de checksum alterado.

Para cada prueba, identifica qué estado inicial crea y qué invariantes verifica.

## 17. Añadir V005

Procedimiento:

1. no editar V001–V004;
2. crear `V005__nombre.sql`;
3. actualizar detección estructural cuando corresponda;
4. actualizar pruebas de secuencia;
5. añadir prueba de fresh install;
6. añadir prueba V004 → V005;
7. actualizar código que use el nuevo esquema;
8. documentar backfill y compatibilidad;
9. ejecutar Ruff, mypy, pytest y Docker.

## 18. Preguntas de entrevista

### ¿Por qué guardar checksum?

Para detectar que el SQL empaquetado ya no coincide con el registrado al aplicar la migración.

### ¿Por qué un advisory lock?

Para serializar migradores cooperantes y evitar carreras sobre la misma versión pendiente.

### ¿Por qué no editar una migración aplicada?

Porque las bases existentes no volverán a ejecutarla; se producirían historias incompatibles con el mismo número de versión.

### ¿Qué diferencia hay entre migration y baseline?

`migration` ejecuta SQL. `baseline` registra una equivalencia estructural ya existente tras revisión explícita.

### ¿Por qué probar V003 → V004?

Porque una instalación limpia no demuestra que una base existente pueda incorporar correctamente raw lineage.

### ¿Por qué no hay downgrade automático?

Porque el DDL inverso puede destruir datos y requiere una estrategia operacional específica.

## 19. Ejercicios personales

### Ejercicio 1

Migra hasta V003 e inspecciona `information_schema.columns`. Luego aplica V004 y explica cada columna nueva.

### Ejercicio 2

En una base desechable, cambia el checksum de V004 en `public.schema_migrations`. Ejecuta `database-validate` y explica el rechazo.

### Ejercicio 3

Diseña V005 para añadir `duration_ms` a `audit.pipeline_runs`. Incluye nullable inicial, backfill, `NOT NULL`, constraint y pruebas de upgrade.

### Ejercicio 4

Crea deliberadamente una estructura con solo `raw_receipt_id`. Explica por qué el detector no debe baselinarla como V004.

## 20. Explicación profesional

> La plataforma utiliza migraciones SQL forward-only empaquetadas y ordenadas. PostgreSQL registra versión, nombre y SHA-256 de cada migración. El motor valida el historial, detecta estructuras conocidas, aplica versiones pendientes dentro de una transacción y utiliza un advisory lock para evitar carreras. V004 introduce lineage de la landing zone raw y está cubierta por pruebas de instalación y upgrade desde V003.
