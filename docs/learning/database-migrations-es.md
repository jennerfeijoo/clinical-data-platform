# Guía de estudio: migraciones formales de PostgreSQL

## Propósito

Esta guía explica cómo el repositorio dejó de crear la base de datos mediante un único archivo `schema.sql` y pasó a utilizar migraciones ordenadas, inmutables y auditables.

El objetivo no es memorizar comandos. Debes poder explicar:

- por qué un esquema monolítico deja de ser suficiente;
- qué diferencia existe entre instalar y actualizar una base de datos;
- cómo se determina qué migraciones ya fueron aplicadas;
- por qué se almacenan checksums;
- por qué el baseline exige una decisión explícita;
- cómo detectar drift entre el código y la base;
- qué ocurre si una migración falla;
- cómo añadir una nueva migración sin alterar las anteriores.

## 1. Problema anterior

El proyecto utilizaba:

```text
sql/schema.sql
```

Ese archivo contenía simultáneamente:

- creación inicial de schemas y tablas;
- `ALTER TABLE` para bases antiguas;
- backfills de columnas nuevas;
- índices;
- lógica de compatibilidad.

El archivo era idempotente en varios puntos mediante `IF NOT EXISTS`, pero no respondía bien estas preguntas:

```text
¿Qué versión tiene esta base?
¿Qué cambios se aplicaron realmente?
¿En qué orden se aplicaron?
¿El SQL aplicado coincide todavía con Git?
¿Una instalación nueva y una actualización recorrieron el mismo camino?
```

Reejecutar un esquema completo tampoco equivale a gestionar evolución. Puede ocultar estados intermedios, tolerar objetos creados manualmente o dificultar la reproducción de una actualización histórica.

## 2. Modelo nuevo

La base evoluciona mediante recursos SQL numerados:

```text
src/clinical_data_platform/migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
└── V003__add_contract_lineage.sql
```

El nombre sigue el patrón:

```text
VNNN__descripcion_en_snake_case.sql
```

Ejemplo:

```text
V003__add_contract_lineage.sql
```

Significa:

```text
V003                 versión ordenada
__                   separador obligatorio
add_contract_lineage nombre descriptivo
.sql                  migración SQL
```

La secuencia debe comenzar en `V001` y ser contigua. No se permite:

```text
V001
V003
```

sin `V002`.

## 3. Qué representa cada migración

### V001

Crea el núcleo original:

- schemas `clinical`, `audit` y `analytics`;
- `audit.pipeline_runs`;
- `clinical.patients`;
- `audit.validation_errors`;
- índices básicos.

### V002

Amplía la plataforma longitudinal:

- añade `entity_id` a los errores;
- crea encuentros;
- crea diagnósticos;
- crea observaciones;
- crea lineage de cohortes;
- crea la tabla analítica de hipertensión;
- añade índices clínicos.

### V003

Añade lineage contractual:

- `contract_path`;
- `contract_version`;
- `contract_sha256`;
- backfill explícito para filas históricas;
- índice por dataset y versión contractual.

La división permite reproducir una actualización real:

```text
V001 → V002 → V003
```

Una base nueva y una base antigua terminan en la misma versión, pero no parten del mismo estado.

## 4. Tabla de historial

El motor crea:

```text
public.schema_migrations
```

La tabla registra:

```text
version
name
checksum
applied_at
execution_ms
execution_type
application_version
```

Ejemplo conceptual:

| version | name | execution_type |
|---:|---|---|
| 1 | create_core_clinical_schema | migration |
| 2 | add_longitudinal_entities_and_cohorts | migration |
| 3 | add_contract_lineage | migration |

`execution_type` puede ser:

```text
migration
baseline
```

## 5. Por qué la tabla está en `public`

La migración V001 es responsable de crear el schema `audit`.

Si el motor necesitara crear `audit.schema_migrations` antes de V001, estaría modificando parte del esquema que la propia V001 pretende crear. Para evitar esa dependencia circular, el historial técnico del migrador vive en:

```text
public.schema_migrations
```

Mientras que el lineage de datos y cohortes vive en:

```text
audit.*
```

## 6. Descubrimiento de migraciones

`discover_migrations()`:

1. inspecciona los recursos empaquetados;
2. filtra nombres válidos;
3. extrae versión y nombre;
4. lee los bytes;
5. calcula SHA-256;
6. ordena por versión;
7. verifica que la secuencia sea contigua;
8. verifica que no haya nombres duplicados.

Cada migración se representa mediante:

```python
Migration(
    version=3,
    name="add_contract_lineage",
    resource_path="V003__add_contract_lineage.sql",
    checksum="...",
    sql="...",
)
```

## 7. Checksum e inmutabilidad

Cuando una migración se aplica, su SHA-256 queda almacenado.

En ejecuciones posteriores el motor compara:

```text
checksum del archivo empaquetado
vs.
checksum guardado en PostgreSQL
```

Si difieren, se genera `MigrationChecksumError`.

Esto impone una regla:

> Una migración aplicada no se edita. Se crea una migración nueva.

Incorrecto:

```text
Modificar V002 después de que fue aplicada
```

Correcto:

```text
Crear V004__correct_observation_constraint.sql
```

El checksum no demuestra que el SQL sea correcto. Demuestra que el archivo actual coincide con el que se registró al aplicarlo.

## 8. Aplicación transaccional

`migrate_database()` ejecuta las migraciones dentro de una transacción PostgreSQL.

La secuencia es:

```text
adquirir advisory lock
→ detectar estado existente
→ crear tabla de historial
→ validar historial
→ ejecutar SQL pendiente
→ insertar registro de migración
→ commit
```

Si una migración falla:

```text
DDL pendiente
+
registro de historial pendiente
```

se revierten juntos.

Por tanto, una migración no debe quedar registrada como aplicada si su SQL no terminó correctamente.

## 9. Advisory lock

El motor ejecuta:

```text
pg_advisory_xact_lock(...)
```

El objetivo es impedir que dos procesos intenten migrar simultáneamente la misma base.

Sin bloqueo podrían ocurrir carreras como:

```text
Proceso A lee current_version = 2
Proceso B lee current_version = 2
A aplica V003
B intenta aplicar V003
```

El advisory lock serializa esa sección crítica durante la transacción.

No reemplaza permisos de base ni coordinación operacional. Controla concurrencia entre procesos que respetan el mismo lock.

## 10. Estado y validación

### Estado

```powershell
clinical-data database-status
```

Informa:

```text
managed
detected
current
latest
pending
```

Distinción importante:

```text
current  = versión registrada en schema_migrations
latest   = versión más alta empaquetada
pending  = migraciones posteriores a current
```

### Validación

```powershell
clinical-data database-validate
```

Comprueba:

- secuencia aplicada contigua;
- nombres coincidentes;
- checksums coincidentes;
- estructura detectada no inferior al historial;
- estructura detectada no superior al historial;
- ausencia de migraciones pendientes.

### Migración

```powershell
clinical-data database-migrate
```

Aplica todas las migraciones pendientes.

También puede detenerse en una versión:

```powershell
clinical-data database-migrate --target-version 1
```

Esto se usa principalmente para pruebas de upgrade.

## 11. Instalación nueva

En una base vacía:

```text
detected_schema_version = 0
history = inexistente
```

El motor:

1. crea `public.schema_migrations`;
2. aplica V001;
3. aplica V002;
4. aplica V003;
5. registra cada una como `migration`.

Una segunda ejecución no aplica nada.

Esto es idempotencia a nivel de historial, no reejecución indiscriminada de todos los SQL.

## 12. Upgrade gestionado

Ejemplo:

```powershell
clinical-data database-migrate --target-version 1
clinical-data database-status
clinical-data database-migrate
```

Después del primer comando:

```text
current = 1
pending = [2, 3]
```

Después del segundo:

```text
current = 3
pending = []
```

Las pruebas verifican que una columna introducida en V003 no exista en V001 y aparezca después del upgrade.

## 13. Baseline de una base existente

Una base creada antes del migrador puede tener todas las tablas pero no `schema_migrations`.

El motor no la adopta automáticamente. Sin autorización explícita produce un error.

Después de revisar la estructura:

```powershell
clinical-data database-migrate --baseline-existing
```

El motor reconoce únicamente estados completos conocidos:

```text
estado equivalente a V001
estado equivalente a V002
estado equivalente a V003
```

Luego registra esas versiones como:

```text
execution_type = baseline
```

Baseline significa:

> El sistema reconoce que la estructura ya existía y registra su equivalencia histórica sin volver a ejecutar esas migraciones.

No significa:

> Cualquier base parecida es segura.

Si detecta un estado parcial, se niega a baselinar.

## 14. Por qué el baseline es explícito

Un baseline automático podría transformar este estado:

```text
algunas tablas existen
algunas columnas fueron modificadas manualmente
no hay historial fiable
```

En una afirmación falsa:

```text
V003 aplicada correctamente
```

La bandera explícita obliga al operador a reconocer que está adoptando una base heredada.

## 15. Downgrades

El motor no implementa migraciones descendentes.

Esto es deliberado. Revertir DDL puede implicar pérdida de datos:

```text
DROP COLUMN
DROP TABLE
cambio de tipo incompatible
```

La estrategia actual es forward-only:

```text
V003 con problema
→ crear V004 correctiva
```

En un sistema real, una reversión operacional puede usar:

- backup y restore;
- despliegue compatible hacia adelante;
- migración correctiva;
- estrategia expand/contract.

No debe confundirse `git revert` con revertir el estado persistente de PostgreSQL.

## 16. Detección de drift

El motor distingue dos formas principales.

### Drift del archivo

```text
checksum empaquetado != checksum registrado
```

Resultado:

```text
MigrationChecksumError
```

### Drift entre estructura e historial

Ejemplo:

```text
schema_migrations dice V001
pero ya existen objetos de V003
```

Resultado:

```text
MigrationHistoryError
```

La detección actual reconoce la evolución V001–V003. Futuras migraciones que introduzcan nuevos hitos estructurales deberán ampliar también la detección de baseline.

## 17. Integración con el resto de la plataforma

Antes de persistir datos, los comandos ejecutan el migrador:

```text
load-dataset
build-hypertension-cohort
run-demo
```

El flujo es:

```text
migrate_database()
→ persist_dataset_validation_outputs()
→ build_hypertension_cohort()
```

La persistencia ya no llama a `apply_schema()` y `sql/schema.sql` fue eliminado.

Esto evita mantener dos mecanismos para modificar la misma base.

## 18. Pruebas implementadas

### Fresh install

Verifica:

```text
0 → 1 → 2 → 3
```

### Reejecución

Verifica que una segunda ejecución no duplique historial ni DDL.

### Upgrade

Verifica:

```text
V001 → V003
```

### Baseline

Crea una estructura heredada sin historial, comprueba que se rechaza y luego la adopta explícitamente.

### Checksum drift

Altera el checksum registrado y comprueba que la validación falla.

### Aislamiento

Cada prueba de integración elimina:

```text
analytics
clinical
audit
public.schema_migrations
```

antes y después de ejecutarse.

## 19. Cómo crear V004

Supón que necesitas añadir:

```text
audit.pipeline_runs.duration_ms
```

Crea:

```text
V004__add_pipeline_duration.sql
```

Contenido conceptual:

```sql
ALTER TABLE audit.pipeline_runs
    ADD COLUMN duration_ms INTEGER;

UPDATE audit.pipeline_runs
SET duration_ms = 0
WHERE duration_ms IS NULL;

ALTER TABLE audit.pipeline_runs
    ALTER COLUMN duration_ms SET NOT NULL,
    ADD CONSTRAINT pipeline_runs_duration_nonnegative
        CHECK (duration_ms >= 0);
```

Después debes:

1. actualizar código que inserta la fila;
2. actualizar pruebas;
3. ejecutar fresh install;
4. ejecutar upgrade desde V003;
5. verificar checksum e historial;
6. no editar V001–V003.

## 20. Preguntas de entrevista

### ¿Por qué eliminaste schema.sql?

> Porque mezclaba instalación inicial y evolución histórica. Las migraciones numeradas permiten conocer el estado de cada base, aplicar solo cambios pendientes, probar upgrades y verificar que el SQL aplicado no fue alterado.

### ¿Por qué usaste un migrador propio?

> El proyecto usa SQL explícito y psycopg, no un ORM. Un migrador pequeño permite mantener el SQL visible y evita introducir Alembic solo para ejecutar scripts. El costo es que debemos mantener descubrimiento, locking, baseline y validación; esa decisión sería reevaluada si el sistema creciera.

### ¿Por qué no editas una migración antigua?

> Porque una migración aplicada forma parte del historial de la base. Editarla haría que una instalación nueva y una base existente recorrieran historias diferentes. Los checksums detectan esa divergencia.

### ¿Qué diferencia hay entre baseline y migration?

> `migration` indica que el motor ejecutó el SQL. `baseline` indica que una estructura existente fue revisada, reconocida como equivalente a una versión y registrada sin volver a ejecutar el SQL.

### ¿Qué ocurre si V003 falla?

> La ejecución de V003 y su inserción en schema_migrations están dentro de la misma transacción. PostgreSQL revierte ambas y la versión no queda marcada como aplicada.

### ¿Por qué un advisory lock?

> Para que dos instancias no calculen el mismo conjunto pendiente y modifiquen el esquema simultáneamente.

## 21. Ejercicios obligatorios

### Ejercicio 1

Ejecuta:

```powershell
clinical-data database-migrate --target-version 1
clinical-data database-status
```

Confirma que encuentros no existe y explica por qué.

### Ejercicio 2

Completa el upgrade:

```powershell
clinical-data database-migrate
clinical-data database-validate
```

Consulta:

```sql
SELECT *
FROM public.schema_migrations
ORDER BY version;
```

Explica cada columna.

### Ejercicio 3

Cambia temporalmente el checksum de V002 en la tabla de historial y ejecuta `database-validate`. Después restaura la base.

Explica por qué cambiar el archivo y cambiar el historial son dos manipulaciones distintas.

### Ejercicio 4

Dibuja de memoria:

```text
packaged SQL
→ discovery
→ checksum validation
→ advisory lock
→ transaction
→ SQL execution
→ history insert
```

### Ejercicio 5

Diseña V004 para añadir `duration_ms`, pero no la publiques hasta poder explicar:

- backfill;
- nulabilidad;
- constraint;
- compatibilidad del código anterior;
- prueba de fresh install;
- prueba de upgrade.

### Ejercicio 6

Argumenta cuándo sería mejor usar Alembic, Flyway o Liquibase en lugar del motor actual.

## 22. Criterio de dominio personal

Puedes afirmar que comprendes esta capa cuando seas capaz de:

- explicar por qué `CREATE TABLE IF NOT EXISTS` no sustituye un historial;
- distinguir fresh install, upgrade y baseline;
- leer una migración y anticipar su efecto;
- añadir V004 sin editar versiones antiguas;
- interpretar un checksum mismatch;
- diagnosticar historia adelantada o estructura adelantada;
- explicar el papel de la transacción y el advisory lock;
- recuperar una base de prueba después de un fallo;
- reconocer los límites del migrador propio.
