# Segunda cohorte reproducible con Synthea

## 1. Qué problema resuelve este hito

Una sola población sintética demuestra que el pipeline puede procesar un conjunto de datos. No demuestra todavía que el sistema pueda distinguir dos poblaciones generadas de forma independiente, mantener sus artefactos separados y evitar que una cohorte sea interpretada como una actualización de la otra.

Este hito añade una segunda cohorte reproducible y una comparación formal entre ambas.

```text
cohorte A
→ perfil A
→ semillas A
→ archivos fuente A
→ adaptación A
→ fingerprint A

cohorte B
→ perfil B
→ semillas B
→ archivos fuente B
→ adaptación B
→ fingerprint B
```

Después se comprueba:

```text
mismo diseño controlado
+ semillas diferentes
+ fingerprints diferentes
+ identificadores completamente disjuntos
```

## 2. Qué significa cohorte en este contexto

Aquí una cohorte es una población sintética completa producida por Synthea bajo un perfil de generación fijado. Incluye seis tipos de entidades:

```text
patients
encounters
diagnoses
observations
medications
procedures
```

No debe confundirse con la cohorte analítica de hipertensión. La cohorte de Synthea representa la población fuente. La cohorte de hipertensión es una selección analítica construida después de cargar datos clínicos.

## 3. Diseño de réplica controlada

Las dos cohortes mantienen iguales:

- versión de Synthea;
- tamaño poblacional;
- fecha de referencia;
- geografía;
- número de hilos;
- años de historia retenidos;
- archivos exportados;
- adaptador y contratos.

Cambian únicamente:

- semilla aleatoria de pacientes;
- semilla de clínicos;
- nombre y hash del perfil.

| Control | Cohorte A | Cohorte B |
|---|---|---|
| Perfil | `synthea-us-small-v1` | `synthea-us-small-cohort-b-v1` |
| Semilla | `20260729` | `20260829` |
| Semilla de clínicos | `20260730` | `20260830` |
| Población | 100 | 100 |
| Fecha | 2026-07-29 | 2026-07-29 |
| Estado | Massachusetts | Massachusetts |

Esta decisión evita confundir variabilidad aleatoria con cambios de diseño. Si al mismo tiempo se cambiara el estado, la fecha o el tamaño, ya no sería posible describir la cohorte B como una réplica bajo las mismas condiciones.

## 4. Por qué no basta con cambiar el nombre de una carpeta

Dos directorios diferentes podrían contener exactamente los mismos pacientes. Por eso la independencia no se deduce de la ruta.

La plataforma examina los identificadores de cada entidad:

| Dataset | Identificador |
|---|---|
| patients | `patient_id` |
| encounters | `encounter_id` |
| diagnoses | `diagnosis_id` |
| observations | `observation_id` |
| medications | `medication_id` |
| procedures | `procedure_id` |

Para cada dominio se exige:

```text
identificador no vacío
identificador único dentro de la cohorte
intersección A ∩ B = conjunto vacío
```

Si aparece un solo identificador compartido, la comparación falla.

## 5. Tres niveles de identidad

### 5.1 Hash del perfil

Identifica los parámetros declarados en el archivo TOML.

```text
profile_sha256
```

Cambiar una semilla, fecha, geografía o versión modifica este hash.

### 5.2 Fingerprint de adaptación

Identifica la transformación completa desde los CSV de Synthea hasta los archivos internos.

Incluye:

```text
versión del adaptador
hash del perfil
archivos fuente
archivos de salida
filas omitidas
```

Dos perfiles distintos no deben producir el mismo fingerprint de adaptación para este experimento.

### 5.3 Fingerprint de comparación

Identifica el par de cohortes y su relación de independencia.

Incluye:

```text
diseño compartido
perfil y semillas de cada cohorte
fingerprint de adaptación de cada cohorte
conteos por dataset
conteos de omisiones
fingerprints de conjuntos de identificadores
conteos de solapamiento
```

No incluye rutas absolutas ni fecha de creación. Por eso mover los directorios o repetir la comparación otro día no cambia el fingerprint mientras el contenido sea el mismo.

## 6. Flujo completo

```text
perfil A ──→ generar A ──→ adaptar A ──→ verificar A ──┐
                                                        ├─→ comparar
perfil B ──→ generar B ──→ adaptar B ──→ verificar B ──┘
                                                        │
                                                        ▼
                                           verificar cero solapamiento
                                                        │
                                                        ▼
                                           cargar A y B por separado
```

## 7. Comandos principales

Listar perfiles:

```powershell
clinical-data-cohort list-profiles
```

Ver el perfil B:

```powershell
clinical-data-cohort profile synthea-us-small-cohort-b-v1
```

Generar las dos cohortes:

```powershell
.\scripts\generate_synthea_cohorts.ps1
```

Regenerar reemplazando workspaces existentes:

```powershell
.\scripts\generate_synthea_cohorts.ps1 -Replace
```

Comparar manualmente:

```powershell
clinical-data-cohort compare `
  data/synthea/synthea-us-small-v1/normalized `
  data/synthea/synthea-us-small-cohort-b-v1/normalized `
  --output-dir data/synthea/cohort-comparison
```

Cargar ambas:

```powershell
.\scripts\load_synthea_cohorts.ps1 -ReplaceComparison
```

## 8. Artefactos de comparación

```text
data/synthea/cohort-comparison/
├── synthea-cohort-comparison.json
├── synthea-cohort-comparison.md
└── synthea-cohort-load.json
```

### `synthea-cohort-comparison.json`

Es la evidencia legible por software. Contiene diseño, perfiles, seeds, conteos, fingerprints y solapamientos.

### `synthea-cohort-comparison.md`

Es un resumen para revisión humana.

### `synthea-cohort-load.json`

Aparece después de una carga completa. Relaciona el fingerprint estable del par con los doce `run_id` de PostgreSQL:

```text
6 datasets × 2 cohortes = 12 ejecuciones
```

## 9. Separación de directorios procesados

```text
data/processed/synthea-cohorts/
├── cohort_a/
│   └── un directorio por dataset
└── cohort_b/
    └── un directorio por dataset
```

Esto evita que los archivos de validación de una cohorte sobrescriban los de la otra.

El raw landing zone puede ser compartido porque su identidad depende del contenido. Sin embargo, cada recepción crea un recibo independiente aunque dos archivos fueran idénticos.

## 10. Protección de la base de datos

Antes de iniciar la primera carga, el comando consulta las seis tablas clínicas. Si cualquiera de los identificadores de A o B ya existe, se detiene.

```text
preflight de identificadores
→ conflicto encontrado
→ no se inicia validación
→ no se crean nuevos pipeline runs
```

Esta protección evita:

- reinterpretar pacientes existentes como miembros de otra cohorte;
- convertir una réplica en una actualización SCD2;
- tolerar eventos duplicados como si fueran una población nueva;
- mezclar dos experimentos sin evidencia explícita.

## 11. Qué ocurre en PostgreSQL

Cada dataset conserva su ciclo normal:

```text
raw_captured
→ validating
→ validated
→ loading
→ completed
```

La carga usa:

```text
iterador tipado
→ COPY FROM STDIN
→ staging temporal
→ merge gobernado
```

Cada cohorte produce seis `run_id` diferentes. Los `run_id` no forman parte del fingerprint reproducible porque identifican ejecuciones concretas y se generan de nuevo en cada corrida.

## 12. Reproducibilidad frente a repetición exacta

La reproducibilidad se evalúa con hashes y fingerprints del contenido. No significa que todos los metadatos sean idénticos.

Pueden cambiar:

```text
created_at
rutas locales
run_id
raw_receipt_id
```

Deben permanecer iguales cuando el contenido no cambia:

```text
profile_sha256
source dataset fingerprint
adaptation fingerprint
identifier fingerprints
comparison fingerprint
```

## 13. Qué valida CI

CI no ejecuta el generador Java completo. Usa dos fixtures pequeños con el mismo esquema de Synthea y con identificadores disjuntos.

Las pruebas comprueban:

1. que los perfiles tienen el mismo diseño y semillas diferentes;
2. que la comparación es determinista;
3. que no existe solapamiento en ninguna entidad;
4. que una cohorte solapada es rechazada;
5. que las dos cohortes pueden cargarse por el pipeline real;
6. que se crean doce ejecuciones completadas;
7. que un segundo intento sobre la misma base se rechaza antes de crear nuevas ejecuciones.

## 14. Qué no demuestra este hito

No demuestra que:

- Massachusetts esté representado epidemiológicamente;
- las prevalencias sintéticas coincidan con datos reales;
- una diferencia entre A y B tenga significado clínico;
- dos cohortes de 100 pacientes sean suficientes para inferencia;
- el sistema esté preparado para PHI;
- la carga de doce datasets sea una transacción global;
- el generador produzca bytes idénticos en cualquier sistema operativo y JVM.

La afirmación correcta es:

> La plataforma puede definir, verificar, comparar y cargar dos poblaciones sintéticas generadas con el mismo diseño y semillas independientes, manteniendo identidad de artefactos, separación de identificadores y linaje de ejecución.

## 15. Ejercicios de aprendizaje

### Ejercicio 1

Cambie únicamente la semilla B, regenere y explique qué fingerprints deberían cambiar.

Resultado esperado:

```text
profile_sha256 B               cambia
source dataset fingerprint B   cambia
adaptation fingerprint B       cambia
comparison fingerprint         cambia
profile_sha256 A               no cambia
```

### Ejercicio 2

Copie los archivos normalizados de A como si fueran B y ejecute la comparación.

Resultado esperado: rechazo por solapamiento de identificadores.

### Ejercicio 3

Mueva ambas carpetas a otra ruta sin modificar archivos y repita la comparación.

Resultado esperado: el fingerprint de comparación permanece igual.

### Ejercicio 4

Cargue el par en una base limpia y consulte:

```sql
SELECT dataset_name, COUNT(*)
FROM audit.pipeline_runs
WHERE status = 'completed'
GROUP BY dataset_name
ORDER BY dataset_name;
```

Resultado esperado: dos ejecuciones completadas por cada uno de los seis datasets.
