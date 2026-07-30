# Ingeniería de releases reproducibles

## 1. Qué problema resuelve este hito

Tener código que funciona en el repositorio no significa que exista un artefacto distribuible confiable.

Una release debe responder preguntas adicionales:

```text
¿Qué versión se está publicando?
¿Qué commit produjo los archivos?
¿El wheel contiene todos los recursos necesarios?
¿La instalación funciona fuera del repositorio?
¿Dos builds equivalentes producen los mismos bytes?
¿Los archivos publicados tienen checksums verificables?
```

La versión `0.21.0` introduce controles para responder esas preguntas antes de crear una release estable `1.0.0`.

## 2. Wheel y source distribution

Python suele distribuir proyectos mediante dos artefactos.

### Wheel

El wheel es un archivo preparado para instalación. Debe contener:

- código Python;
- metadata del paquete;
- entrypoints de consola;
- contratos;
- migraciones;
- perfiles Synthea;
- definición SQL de la cohorte;
- marcador `py.typed`.

No debe contener pruebas, documentación interna, workflows, reportes de seguridad ni datos generados.

### Source distribution

El `sdist` contiene el código fuente y los materiales necesarios para reconstruir y revisar el proyecto. Puede incluir documentación, pruebas, scripts, SQL y datos sintéticos pequeños, pero debe excluir artefactos generados, credenciales, entornos locales y datos procesados.

## 3. Por qué no basta con ejecutar `python -m build`

Un build puede terminar correctamente y aun así producir un wheel incompleto.

Ejemplo:

```text
repositorio
├── sql/cohorts/hypertension.sql
└── paquete Python
```

Si el SQL solo existe fuera del paquete, el comando puede funcionar desde el repositorio y fallar después de instalar el wheel en otro directorio.

Por eso la definición de cohorte también se empaqueta dentro de:

```text
clinical_data_platform/cohort_definitions/hypertension.sql
```

Una prueba exige que la copia de desarrollo y el recurso empaquetado sean idénticos.

## 4. Consistencia de versión

La versión aparece en varias superficies:

```text
pyproject.toml
__init__.py
CHANGELOG.md
CITATION.cff
README.md
prueba del paquete
CI
Git tag
```

Una discrepancia puede producir situaciones ambiguas, por ejemplo:

```text
tag v1.0.0
wheel 0.21.0
changelog 1.0.0
```

`scripts/check_release.py` rechaza ese estado. Para una release válida, todas las fuentes deben declarar exactamente el mismo valor.

## 5. Verificación de contenidos

`scripts/verify_distribution.py` abre realmente el wheel y el `sdist`.

No confía únicamente en los nombres de archivo. Comprueba:

```text
version de METADATA
Requires-Python
entrypoints
recursos empaquetados
conteo de migraciones
presencia de perfiles
archivos obligatorios del sdist
rutas prohibidas
SHA-256 de cada artefacto
```

El resultado se guarda en `release-manifest.json` y los hashes en `SHA256SUMS`.

## 6. Instalación limpia

Las pruebas normales usan una instalación editable:

```bash
python -m pip install -e .
```

Ese modo puede leer archivos directamente desde el repositorio. Por tanto, puede ocultar que el wheel está incompleto.

El gate de release crea otro entorno virtual e instala el wheel construido:

```text
repositorio → build → wheel
                     ↓
              entorno limpio
                     ↓
        ejecución fuera del repositorio
```

Después verifica contratos, perfiles, migraciones, entrypoints y la definición SQL empaquetada.

## 7. Build reproducible

El workflow construye los artefactos dos veces con:

```text
SOURCE_DATE_EPOCH = timestamp del commit
```

Después compara los archivos byte por byte.

```text
build A wheel  ─┐
                ├── deben ser idénticos
build B wheel  ─┘

build A sdist  ─┐
                ├── deben ser idénticos
build B sdist  ─┘
```

Esto reduce diferencias causadas por timestamps y orden no determinista.

La evidencia solo es válida para el entorno registrado. No garantiza que cualquier sistema operativo o versión futura de las herramientas produzca los mismos bytes.

## 8. Relación entre commit, tag y release

La cadena de procedencia es:

```text
commit validado
→ tag vX.Y.Z
→ workflow del tag
→ wheel y sdist
→ checksums y manifest
→ GitHub Release
```

El tag no debe moverse después de publicar la release. Si se descubre un defecto, se crea una nueva versión.

Reemplazar silenciosamente un archivo con el mismo nombre destruye la trazabilidad porque dos usuarios podrían tener bytes diferentes para una supuesta misma versión.

## 9. Por qué PyPI no se activa todavía

Publicar en PyPI es una acción externa e irreversible desde la perspectiva del nombre y de los consumidores.

Antes se requiere:

- revisar disponibilidad y propiedad del nombre;
- configurar Trusted Publishing;
- limitar permisos mediante OpenID Connect;
- evaluar el compromiso de soporte público;
- probar el proceso de empaquetado y release.

La versión `0.21.0` prepara y valida el mecanismo, pero mantiene GitHub Releases como canal gobernado.

## 10. Qué demuestra este hito

Demuestra que el proyecto puede:

- sincronizar metadata de versión;
- construir wheel y `sdist`;
- verificar su contenido;
- generar checksums;
- reproducir los artefactos en el entorno de CI;
- instalar y ejecutar el wheel fuera del repositorio;
- crear una GitHub Release desde un tag válido.

No demuestra:

- validez clínica;
- seguridad completa;
- reproducibilidad universal;
- soporte de producción;
- preparación para PHI;
- disponibilidad permanente del proyecto.
