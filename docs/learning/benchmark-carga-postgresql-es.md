# Guía de estudio: benchmark reproducible de carga PostgreSQL

## 1. Por qué se necesita este hito

Implementar `COPY` no demuestra por sí solo que la nueva ruta sea más rápida. Una afirmación de rendimiento necesita:

```text
pregunta delimitada
método de referencia
misma carga para ambos métodos
entorno registrado
repeticiones
métrica definida
verificación de equivalencia
resultados completos
límites de interpretación
```

La pregunta estudiada es:

> ¿Cuánto cambia el tiempo de carga inicial cuando la plataforma usa COPY a staging temporal y merge por conjuntos, comparado con su ruta previa basada en `executemany`, manteniendo activo el mismo modelo clínico gobernado?

## 2. Prueba, benchmark y perfilado

### Prueba funcional

Comprueba propiedades como:

```text
se insertaron todas las filas
se creó el historial SCD2
se resolvió la terminología
se rechazó un conflicto inmutable
los dos métodos dejaron el mismo contenido
```

### Benchmark

Mide:

```text
tiempo por método
mediana
variabilidad
filas por segundo
cambio al aumentar el tamaño
```

### Perfilado

Busca explicar en qué se consume el tiempo:

```text
CPU de Python
conversión de tipos
transferencia del driver
triggers
índices
WAL
I/O
esperas de PostgreSQL
```

Este hito es un benchmark con tiempos por entidad. No es todavía un perfilador completo de CPU, memoria, WAL o I/O.

## 3. Métodos comparados

### Ruta COPY

```text
registros sintéticos
→ row_builder
→ tipos Python
→ COPY FROM STDIN
→ tabla temporal
→ INSERT ... SELECT
→ ON CONFLICT
→ triggers y constraints
→ COMMIT
```

### Ruta de referencia

```text
registros sintéticos
→ row_builder
→ tipos Python
→ executemany
→ INSERT ... ON CONFLICT
→ triggers y constraints
→ COMMIT
```

`executemany` es la ruta previa de la aplicación. No representa todas las estrategias posibles de batching en PostgreSQL.

## 4. Qué permanece activo

La comparación no desactiva elementos costosos para fabricar un resultado favorable. Permanecen activos:

```text
foreign keys
check constraints
índices
triggers terminológicos
normalized_concept_id
record_sha256
patient_history
protección de eventos inmutables
source_run_id
commits durables
```

Por eso hablamos de **carga gobernada**, no de escritura en una tabla sin reglas.

## 5. Qué queda fuera del reloj

Se excluyen:

```text
generación de la población
captura raw
validación contractual
archivos valid/invalid
quality report
execution journal completo
verificación posterior
serialización de artefactos
```

Esto permite aislar el kernel de persistencia, pero limita la conclusión: no puede afirmarse que el pipeline completo mejore en el mismo porcentaje.

## 6. Carga sintética

Cada paciente produce quince filas:

| Entidad | Filas por paciente |
|---|---:|
| patients | 1 |
| encounters | 2 |
| diagnoses | 2 |
| observations | 6 |
| medications | 2 |
| procedures | 2 |
| Total | 15 |

Por tanto:

```text
250 pacientes   → 3 750 filas
1 000 pacientes → 15 000 filas
2 500 pacientes → 37 500 filas
```

Las seis observaciones corresponden a dos encuentros con tres mediciones cada uno:

```text
presión sistólica
presión diastólica
frecuencia cardiaca
```

## 7. Determinismo

El generador fija:

```text
seed = 20260729
reference_date = 2026-07-29
```

La misma versión de código, seed y tamaño produce el mismo contenido lógico y fingerprint de workload.

| Pacientes | Fingerprint del workload |
|---:|---|
| 250 | `75ec4629b209e403752991878e57dfa546605d1b8954a71ca8845417f84bca61` |
| 1 000 | `f94c3726aa7c95b53da035b807c12f6dae70455bafad7e2e334621b43956ccea` |
| 2 500 | `fc6e01c7309147a1eab076d86834970ebcd19446a904fdb8b6ec0aa1fc79194f` |

El fingerprint identifica contenido; no demuestra representatividad clínica.

## 8. Warm-up

La primera ejecución puede pagar costes de inicialización distintos:

```text
carga de módulos
preparación de rutas
páginas fuera de caché
inicialización de estructuras
```

Se ejecuta un calentamiento por método y tamaño. Su tiempo no entra en los agregados.

## 9. Por qué se usan seis repeticiones

Con dos métodos y orden alternado, un número impar produce desequilibrio. Cinco repeticiones darían:

```text
COPY primero: 3 veces
executemany primero: 2 veces
```

El protocolo definitivo usa seis:

```text
R1: COPY → executemany
R2: executemany → COPY
R3: COPY → executemany
R4: executemany → COPY
R5: COPY → executemany
R6: executemany → COPY
```

Así cada método aparece primero tres veces y segundo tres veces. La CLI rechaza cantidades impares.

## 10. Seguridad de la base de datos

El benchmark elimina el estado de la plataforma entre trials. Por eso exige:

```text
--allow-destructive-reset
```

La confirmación no es la única defensa. Después de migrar, la CLI inspecciona todas las tablas base de:

```text
audit
clinical
analytics
```

Si alguna contiene filas, el benchmark se detiene. No intenta distinguir datos de prueba de datos valiosos.

La regla operativa es:

```text
usar una base dedicada, vacía y descartable
```

## 11. Reloj

El código usa:

```python
perf_counter_ns()
```

Es monotónico y apropiado para intervalos.

```text
elapsed_ms = (fin_ns - inicio_ns) / 1 000 000
```

`datetime.now()` se usa para fechar el reporte, no para medir duración.

## 12. Throughput

```text
rows_per_second = total_rows / elapsed_seconds
```

Ejemplo:

```text
37 500 filas / 7.936444 s ≈ 4 725.0 filas/s
```

La tasa mezcla entidades con diferente coste. No equivale a pacientes por segundo.

## 13. Mediana, media y variabilidad

La media usa todos los tiempos y es sensible a outliers.

Con seis repeticiones ordenadas:

```text
t1 ≤ t2 ≤ t3 ≤ t4 ≤ t5 ≤ t6
mediana = (t3 + t4) / 2
```

El benchmark usa la mediana como cifra principal, pero conserva:

```text
media
desviación estándar
mínimo
máximo
mediana
```

## 14. Speedup

```text
speedup = mediana_executemany / mediana_COPY
```

Para 2 500 pacientes:

```text
10 955.541 / 7 936.444 ≈ 1.380×
```

No debe expresarse como «138% más rápido».

## 15. Reducción de tiempo

```text
reducción = (1 - COPY / executemany) × 100
```

Para el mismo tamaño:

```text
(1 - 7 936.444 / 10 955.541) × 100 ≈ 27.56%
```

## 16. Resultado equilibrado de referencia

| Pacientes | Filas | COPY | `executemany` | Speedup | Reducción |
|---:|---:|---:|---:|---:|---:|
| 250 | 3 750 | 825.694 ms | 1 083.028 ms | 1.312× | 23.76% |
| 1 000 | 15 000 | 3 183.671 ms | 4 341.867 ms | 1.364× | 26.68% |
| 2 500 | 37 500 | 7 936.444 ms | 10 955.541 ms | 1.380× | 27.56% |

La ventaja fue consistente y aumentó con el tamaño dentro de este rango.

## 17. Verificación de equivalencia

Un método podría parecer más rápido porque omitió trabajo. Después de cada trial se comprueba:

```text
conteo de cada tabla
conteo de patient_history
filas is_current
conteo terminológico
record_sha256 ordenados
fingerprint combinado de base
```

Los doce trials de cada tamaño deben producir el mismo fingerprint:

| Pacientes | Fingerprint de base gobernada |
|---:|---|
| 250 | `d8774d0544ed3e54645ab416d457bc71d148de15d82b998b397cfaa287ba6671` |
| 1 000 | `0de3fb68be7f9d01ddc6cf6d7ce929ecf7c15c1f1b8a5bd0f4d780b633cf8b2a` |
| 2 500 | `c224fd2dac09e27af51186c2986d3efb05a305fb0d68a8356b8af6061821a8e7` |

## 18. Workload fingerprint y database fingerprint

### Workload fingerprint

Identifica la entrada sintética.

### Database-content fingerprint

Identifica la salida después de:

```text
conversión de tipos
triggers
hashes
terminología
historial
```

Separarlos permite detectar misma entrada con salida distinta.

## 19. Entorno registrado

La referencia se ejecutó con:

```text
GitHub Actions
4 CPU lógicas visibles
AMD EPYC 7763
~16.77 GB RAM visible
Python 3.11.15
PostgreSQL 16.14
shared_buffers = 128MB
fsync = on
full_page_writes = on
synchronous_commit = on
wal_level = replica
```

El nombre «64-Core Processor» describe el modelo del host. El job veía cuatro CPU lógicas, no sesenta y cuatro cores exclusivos.

## 20. Evidencia anterior y por qué no es la referencia

Una corrida previa usó cinco repeticiones y observó aceleraciones alrededor de 1.38–1.42×. Está preservada por trazabilidad, pero COPY ocupaba la primera posición tres veces y la referencia solo dos.

No se borró ni se ocultó. Se clasificó como evidencia supersedida y se repitió el experimento con orden equilibrado.

## 21. Por qué no se reporta memoria máxima

`tracemalloc` no captura de forma completa:

```text
proceso PostgreSQL
buffers nativos de psycopg
kernel y page cache
contenedor de servicio
```

Presentar memoria Python como memoria total sería engañoso.

## 22. Por qué no hay intervalos de confianza

Seis repeticiones ofrecen evidencia descriptiva, no inferencia estadística robusta sobre infraestructura compartida. Se reportan mediana y dispersión, sin p-values ni intervalos que aparenten más certeza.

## 23. Cómo ejecutarlo

PowerShell:

```powershell
python -m pip install -e ".[dev]"
docker compose up -d postgres

$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"

clinical-data-benchmark `
    --allow-destructive-reset `
    --patients 250 1000 2500 `
    --repetitions 6 `
    --warmups 1 `
    --seed 20260729 `
    --output-dir data/benchmarks/loading
```

También puede usarse:

```powershell
.\scripts\run_benchmark.ps1
```

El comando fallará si encuentra cualquier fila en los schemas gobernados.

## 24. Artefactos

### `benchmark-results.json`

Documento completo legible por máquinas:

```text
configuración
entorno
workloads
trials
agregados
comparaciones
límites
```

### `benchmark-trials.csv`

Una fila por trial para análisis en R, Python o una hoja de cálculo.

### `benchmark-summary.md`

Resumen para GitHub y revisión humana.

## 25. Evidencia permanente

```text
benchmarks/loading/github-actions-run-30470147850/
├── benchmark-summary.md
├── benchmark-trials.csv
└── reference-run.json
```

`reference-run.json` conserva:

```text
workflow run ID
head SHA
artifact ID y digest
hashes de archivos originales
configuración
entorno
agregados
comparaciones
límites
```

## 26. Workflow dedicado

```text
.github/workflows/benchmark.yml
```

Se separa del CI ordinario porque el benchmark completo:

```text
tarda más
consume más base de datos
varía con la infraestructura
no debe ejecutarse por cambios no relacionados
```

El CI normal ejecuta un benchmark pequeño de integración. El workflow dedicado genera la evidencia de rendimiento.

## 27. Afirmación respaldada

> En el entorno registrado de GitHub Actions, para cargas iniciales deterministas de 3 750 a 37 500 filas sobre el esquema gobernado de seis entidades, COPY con staging temporal y merge redujo la mediana de tiempo entre 23.76% y 27.56% frente a la ruta previa basada en `executemany`.

## 28. Afirmaciones no respaldadas

```text
COPY siempre es 25% más rápido.
Todo el pipeline mejoró 25%.
El sistema soporta producción hospitalaria.
La tasa será igual con millones de filas.
La memoria disminuyó en un porcentaje conocido.
El resultado será igual con PostgreSQL remoto.
El resultado será igual con múltiples escritores.
```

## 29. Limitaciones

1. GitHub Actions es infraestructura compartida.
2. Seis repeticiones siguen siendo pocas para inferencia formal.
3. Solo se miden inserciones iniciales.
4. Hay un solo escritor.
5. PostgreSQL está en un contenedor local.
6. La carga es sintética y regular.
7. El máximo es 37 500 filas.
8. Validación y auditoría completa están fuera del reloj.
9. No se mide memoria total.
10. No se miden bytes de WAL, CPU ni I/O.

## 30. Ejercicios

### Ejercicio 1

Explica por qué desactivar triggers haría la comparación menos útil.

### Ejercicio 2

Para COPY = 2.4 s y referencia = 3.6 s:

```text
speedup = 3.6 / 2.4 = 1.5×
reducción = (1 - 2.4 / 3.6) × 100 = 33.33%
```

### Ejercicio 3

Explica por qué cinco repeticiones no equilibran AB/BA y seis sí.

### Ejercicio 4

Describe un caso en el que alternar el orden no elimine toda la variabilidad:

```text
thermal throttling
contención externa repentina
mantenimiento del host
caché no reproducible
```

### Ejercicio 5

¿Por qué 4 725 filas/s no significa 4 725 pacientes/s?

Porque cada paciente genera quince filas y cada entidad tiene costes distintos.

### Ejercicio 6

Diseña un perfil separado para estudiar actualizaciones o conflictos inmutables sin mezclarlos con carga inicial.

## 31. Lectura recomendada del código

```text
1. BenchmarkConfiguration
2. generate_benchmark_workload
3. _rowwise_upsert_statement
4. _load_with_copy
5. _load_with_executemany
6. _execute_trial
7. _database_evidence
8. _aggregate_trials
9. _comparisons
10. run_loading_benchmark
11. benchmark_cli.py
12. benchmark.yml
13. tests/test_benchmark.py
```

La idea central es que rendimiento y corrección se validan juntos: ningún tiempo se publica sin verificar que ambos métodos dejaron el mismo contenido gobernado.
