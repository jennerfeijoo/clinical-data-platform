# Guía de estudio: benchmark reproducible de carga PostgreSQL

## 1. Qué problema resuelve este hito

Implementar `COPY` no demuestra por sí solo que la nueva ruta sea más rápida. Para sostener una afirmación de rendimiento se necesitan, como mínimo:

```text
una pregunta delimitada
un método de referencia
la misma carga para ambos métodos
un entorno registrado
repeticiones
una métrica definida
verificación de equivalencia
resultados sin seleccionar solo la mejor ejecución
límites de interpretación
```

Este hito convierte la frase informal «COPY debería ser más rápido» en una comparación ejecutable y auditable.

La pregunta estudiada es:

> ¿Cuánto cambia el tiempo de carga inicial cuando la plataforma usa COPY a staging temporal y merge por conjuntos, comparado con su ruta previa basada en `executemany`, manteniendo activo el mismo modelo clínico gobernado?

## 2. Benchmark, prueba y perfilado no son lo mismo

### Prueba funcional

Responde preguntas como:

```text
¿se insertaron todas las filas?
¿se rechazó un conflicto inmutable?
¿se creó el historial SCD2?
¿los dos métodos producen el mismo contenido?
```

Una prueba puede afirmar correcto o incorrecto. No necesita medir rendimiento con precisión.

### Benchmark

Responde preguntas como:

```text
¿cuánto tarda cada método?
¿cuál es la mediana?
¿cuántas filas por segundo procesa?
¿cómo cambia la diferencia al aumentar el tamaño?
```

Un benchmark necesita repetición, entorno y protocolo.

### Perfilado

Busca explicar dónde se consume el tiempo:

```text
CPU de Python
conversión de tipos
red o socket
triggers
índices
WAL
I/O
esperas de PostgreSQL
```

Este hito incluye tiempos por entidad, pero no es todavía un perfilador completo de CPU, memoria, WAL o I/O.

## 3. Qué significa «benchmark documentado»

No basta con guardar una tabla de tiempos. El benchmark del repositorio incluye:

1. Generador de carga determinista.
2. Dos métodos explícitos.
3. Igual esquema, datos y reglas para ambos.
4. Warm-up.
5. Cinco repeticiones medidas.
6. Orden alternado AB/BA.
7. Medición con reloj monotónico de alta resolución.
8. Verificación del contenido final.
9. Registro del entorno.
10. Exportación JSON, CSV y Markdown.
11. Workflow independiente en GitHub Actions.
12. Evidencia de referencia versionada.
13. Declaración de lo que no fue medido.

## 4. El kernel medido

El benchmark no mide todo el pipeline. Mide el núcleo de persistencia gobernada.

### Ruta COPY

```text
registros sintéticos en memoria
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
registros sintéticos en memoria
→ row_builder
→ tipos Python
→ executemany
→ INSERT ... ON CONFLICT
→ triggers y constraints
→ COMMIT
```

Esta comparación intenta aislar la diferencia de estrategia de transferencia y reconciliación.

## 5. Qué permanece activo

Una comparación rápida pero artificial podría desactivar elementos costosos. Aquí no se hace eso.

Permanecen activos:

```text
foreign keys
check constraints
índices
triggers terminológicos
normalized_concept_id
record_sha256
historial patient_history
protección de eventos inmutables
source_run_id
commits durables
```

Por eso el resultado describe «carga gobernada» y no solo escritura en una tabla vacía sin reglas.

## 6. Qué se excluye del reloj

Quedan fuera:

```text
generación de la población
captura raw
hash del archivo raw
validación contractual
escritura de archivos valid/invalid
quality report
registro completo del execution journal
verificación posterior del contenido
serialización de artefactos
```

La exclusión evita atribuir a COPY tiempo perteneciente a otras etapas.

También limita la conclusión: no se puede afirmar que el pipeline completo sea 29% más rápido.

## 7. Construcción de la carga sintética

Cada paciente produce quince registros clínicos:

| Entidad | Registros por paciente |
|---|---:|
| Paciente | 1 |
| Encuentros | 2 |
| Diagnósticos | 2 |
| Observaciones | 6 |
| Medicaciones | 2 |
| Procedimientos | 2 |
| Total | 15 |

Por tanto:

```text
250 pacientes   → 3 750 filas
1 000 pacientes → 15 000 filas
2 500 pacientes → 37 500 filas
```

Las observaciones representan seis filas por paciente porque cada uno tiene dos encuentros y tres mediciones por encuentro:

```text
presión sistólica
presión diastólica
frecuencia cardiaca
```

## 8. Determinismo

El generador fija:

```text
seed = 20260729
reference_date = 2026-07-29
```

Una misma combinación de código, seed y número de pacientes produce el mismo contenido lógico y el mismo fingerprint de workload.

Los fingerprints de la ejecución de referencia fueron:

| Pacientes | Fingerprint del workload |
|---:|---|
| 250 | `75ec4629b209e403752991878e57dfa546605d1b8954a71ca8845417f84bca61` |
| 1 000 | `f94c3726aa7c95b53da035b807c12f6dae70455bafad7e2e334621b43956ccea` |
| 2 500 | `fc6e01c7309147a1eab076d86834970ebcd19446a904fdb8b6ec0aa1fc79194f` |

Un fingerprint no demuestra que el dataset sea clínicamente representativo. Solo identifica el contenido exacto generado por ese protocolo.

## 9. Warm-up

La primera ejecución puede pagar costes que las siguientes no pagan de la misma forma:

```text
carga de módulos
creación de conexiones internas
compilación o preparación de rutas
páginas no presentes en caché
inicialización de estructuras
```

Por eso se ejecuta una repetición de calentamiento por método y tamaño. Su resultado se descarta de los agregados.

Warm-up no significa modificar manualmente los resultados. Es una fase declarada del protocolo.

## 10. Alternancia AB/BA

Un diseño ingenuo sería:

```text
COPY cinco veces
luego executemany cinco veces
```

Ese orden puede favorecer a uno de los métodos por cambios temporales del runner.

El benchmark alterna:

```text
R1: COPY → executemany
R2: executemany → COPY
R3: COPY → executemany
R4: executemany → COPY
R5: COPY → executemany
```

Así ambos métodos aparecen primero y segundo durante la serie.

## 11. Reloj utilizado

El código usa:

```python
perf_counter_ns()
```

Es apropiado para intervalos porque es monotónico: no retrocede por ajustes del reloj del sistema.

La conversión es:

```text
elapsed_ms = (fin_ns - inicio_ns) / 1 000 000
```

No se utiliza `datetime.now()` para calcular duración. `datetime` se usa para sellar el momento de generación del reporte, no para medir intervalos.

## 12. Throughput

La tasa se calcula como:

```text
rows_per_second = total_rows / elapsed_seconds
```

Ejemplo con 37 500 filas y 6.465960 segundos:

```text
37 500 / 6.465960 ≈ 5 799.6 filas/s
```

Esta tasa incluye entidades con distinta complejidad. No debe interpretarse como una tasa uniforme de «registros hospitalarios».

## 13. Mediana y media

### Media

Suma todos los tiempos y divide por el número de repeticiones.

Es sensible a una ejecución anormalmente lenta.

### Mediana

Ordena los cinco tiempos y toma el valor central.

Con cinco observaciones:

```text
t1 ≤ t2 ≤ t3 ≤ t4 ≤ t5
mediana = t3
```

El benchmark usa la mediana para la comparación principal, pero conserva media, desviación estándar, mínimo y máximo.

## 14. Speedup

La aceleración se define como:

```text
speedup = mediana_executemany / mediana_COPY
```

Para 2 500 pacientes:

```text
9 176.855 ms / 6 465.960 ms ≈ 1.419
```

Interpretación:

```text
COPY fue aproximadamente 1.419 veces tan rápido
```

No significa que «COPY fue 141.9% más rápido».

## 15. Reducción del tiempo

La reducción relativa es:

```text
reducción = (1 - mediana_COPY / mediana_executemany) × 100
```

Para 2 500 pacientes:

```text
(1 - 6 465.960 / 9 176.855) × 100 ≈ 29.54%
```

Speedup y reducción expresan la misma comparación con escalas diferentes.

## 16. Resultados de referencia

| Pacientes | Filas | COPY | `executemany` | Speedup | Reducción |
|---:|---:|---:|---:|---:|---:|
| 250 | 3 750 | 671.737 ms | 928.806 ms | 1.383× | 27.68% |
| 1 000 | 15 000 | 2 615.950 ms | 3 693.506 ms | 1.412× | 29.17% |
| 2 500 | 37 500 | 6 465.960 ms | 9 176.855 ms | 1.419× | 29.54% |

La ventaja fue consistente en los tres tamaños y aumentó ligeramente con la carga.

## 17. Verificación de equivalencia

Medir dos métodos sin verificar el resultado podría premiar al método que omitió trabajo.

Después de cada trial se comprueba:

```text
conteo de cada tabla
conteo del historial
filas current del historial
conteo de códigos normalizados
hashes record_sha256 ordenados
fingerprint combinado de base de datos
```

Los diez trials de cada tamaño deben generar el mismo fingerprint.

Esto confirma igualdad dentro de las propiedades verificadas. No constituye una demostración formal de equivalencia de todos los estados posibles.

## 18. Por qué el fingerprint del workload y el de la base son distintos

### Workload fingerprint

Identifica los registros sintéticos de entrada.

### Database-content fingerprint

Identifica el contenido gobernado producido después de:

```text
conversión de tipos
triggers
hashes de registros
normalización terminológica
historial
```

Separarlos permite detectar:

```text
misma entrada, salida diferente
entrada diferente, salida aparentemente igual
```

## 19. Entorno de referencia

La medición depende del entorno. La referencia registró:

```text
GitHub Actions
4 CPU lógicas visibles
AMD EPYC 9V74
~16.77 GB RAM visible
Python 3.11.15
PostgreSQL 16.14
shared_buffers = 128MB
fsync = on
full_page_writes = on
synchronous_commit = on
wal_level = replica
```

El nombre «80-Core Processor» pertenece al modelo del host. El job disponía de cuatro CPU lógicas, no de ochenta cores exclusivos.

## 20. Variabilidad

La ejecución de referencia no fue la única.

Una corrida anterior observó:

| Pacientes | Speedup anterior | Speedup referencia |
|---:|---:|---:|
| 250 | 1.380× | 1.383× |
| 1 000 | 1.407× | 1.412× |
| 2 500 | 1.423× | 1.419× |

La cercanía es tranquilizadora, pero dos corridas no describen toda la variabilidad futura de GitHub Actions.

## 21. Por qué no se reporta memoria máxima

`tracemalloc` mide asignaciones administradas por Python. No captura de forma completa:

```text
memoria del proceso PostgreSQL
buffers del driver nativo
kernel y page cache
memoria del contenedor de servicio
```

Reportar solo memoria Python como «memoria total» sería engañoso.

Una comparación de memoria responsable requeriría medición coordinada de procesos y contenedores, por ejemplo con límites y métricas del sistema operativo.

## 22. Por qué no se usan intervalos de confianza

Cinco repeticiones permiten una descripción básica, pero no bastan para hacer inferencia estadística robusta sobre una población estable de tiempos, especialmente en infraestructura compartida.

El reporte usa:

```text
mediana
media
desviación estándar
mínimo
máximo
```

No presenta p-values ni intervalos de confianza que aparenten más certeza de la disponible.

## 23. Cómo ejecutar el benchmark

PowerShell:

```powershell
python -m pip install -e ".[dev]"
docker compose up -d postgres

$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"

clinical-data-benchmark `
    --patients 250 1000 2500 `
    --repetitions 5 `
    --warmups 1 `
    --seed 20260729 `
    --output-dir data/benchmarks/loading
```

Advertencia operativa:

```text
el benchmark elimina el estado de las tablas de la plataforma antes de cada trial
```

Debe ejecutarse en una base aislada y descartable.

## 24. Artefactos generados

### `benchmark-results.json`

Contiene el documento completo y legible por máquinas:

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

Una fila por trial, útil para R, Python, Excel o análisis adicional.

### `benchmark-summary.md`

Resumen legible en GitHub y en el Step Summary del workflow.

## 25. Evidencia permanente

La referencia está en:

```text
benchmarks/loading/github-actions-run-30466706538/
```

El directorio conserva:

```text
benchmark-summary.md
benchmark-trials.csv
reference-run.json
```

`reference-run.json` añade el ID del workflow, ID y digest del artifact, SHA del head y hashes de los archivos fuente del artifact.

## 26. Workflow dedicado

Archivo:

```text
.github/workflows/benchmark.yml
```

Se separa del CI ordinario porque un benchmark completo:

```text
tarda más
consume más base de datos
puede variar por infraestructura
no debe bloquear cambios de documentación no relacionados
```

El CI ordinario conserva un benchmark pequeño como prueba de integración. El workflow dedicado genera la evidencia de rendimiento.

## 27. Qué afirmación sí está respaldada

La formulación responsable es:

> En el entorno registrado de GitHub Actions, para cargas iniciales deterministas de 3 750 a 37 500 filas sobre el esquema gobernado de seis entidades, COPY con staging temporal y merge redujo la mediana de tiempo entre 27.68% y 29.54% frente a la ruta previa basada en `executemany`.

## 28. Afirmaciones no respaldadas

No debe afirmarse:

```text
COPY siempre es 30% más rápido.
Todo el pipeline mejoró 30%.
El sistema soporta producción hospitalaria.
El sistema cargará millones de filas a la misma tasa.
La memoria disminuyó 30%.
La ventaja será igual con PostgreSQL remoto.
La ventaja será igual con múltiples escritores.
```

## 29. Ejercicios de comprensión

### Ejercicio 1

Explica por qué desactivar triggers haría la comparación menos relevante para esta plataforma.

### Ejercicio 2

Calcula el speedup para:

```text
COPY = 2.4 s
referencia = 3.6 s
```

Resultado esperado:

```text
3.6 / 2.4 = 1.5×
```

### Ejercicio 3

Calcula la reducción del tiempo para el mismo ejemplo.

```text
(1 - 2.4 / 3.6) × 100 = 33.33%
```

### Ejercicio 4

Describe una situación en la que alternar AB/BA no eliminaría el sesgo por completo.

Ejemplos válidos:

```text
contención externa que cambia abruptamente
thermal throttling
mantenimiento del host
una caché que nunca vuelve al mismo estado
```

### Ejercicio 5

¿Por qué una tasa de 5 800 filas/s no implica que 5 800 pacientes/s puedan procesarse?

Porque un paciente genera quince filas y las entidades tienen costes diferentes.

### Ejercicio 6

Diseña un perfil adicional para estudiar actualizaciones de pacientes y conflictos de eventos sin mezclarlo con el benchmark de carga inicial.

## 30. Lectura recomendada del código

Orden sugerido:

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

La idea central es que rendimiento y corrección se miden juntos: ningún tiempo se publica sin verificar primero que ambos métodos dejaron el mismo contenido gobernado.
