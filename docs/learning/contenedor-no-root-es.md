# Contenedor no root y endurecimiento del runtime

## 1. Qué problema resuelve este hito

Un contenedor puede estar aislado del host y aun así ejecutar su proceso principal como `root` dentro del namespace. Eso no equivale automáticamente a root del host, pero aumenta el impacto potencial de una vulnerabilidad, una mala configuración o un escape del contenedor.

La versión `0.20.0` exige que la aplicación se ejecute con una identidad no privilegiada y que los comandos reales funcionen bajo restricciones adicionales.

```text
usuario fijo no root
+ filesystem raíz de solo lectura
+ capacidades Linux eliminadas
+ no-new-privileges
+ /tmp limitado
+ volúmenes de salida explícitos
```

## 2. Identidad fija

La imagen crea:

```text
usuario: clinical
UID: 10001
GID: 10001
home: /home/clinical
shell: /usr/sbin/nologin
```

El Dockerfile termina con:

```dockerfile
USER 10001:10001
```

La identidad numérica es importante porque un volumen montado desde el host se evalúa mediante UID y GID, no por el nombre `clinical`.

## 3. Por qué no basta con añadir `USER`

Una imagen podría declarar un usuario no root y seguir dependiendo de permisos de root en algún flujo real.

Ejemplos:

```text
el comando solo funciona porque /app es escribible
la captura raw escribe archivos como root
la migración requiere una carpeta temporal no declarada
la aplicación intenta instalar paquetes al arrancar
un script cambia permisos mediante una capability
```

Por eso CI no se limita a leer el Dockerfile. Ejecuta contratos, perfiles, acceso PostgreSQL y raw capture con el usuario efectivo `10001`.

## 4. Root filesystem de solo lectura

La ejecución usa:

```bash
--read-only
```

Esto impide modificar la capa del contenedor durante la ejecución. Si el programa intenta escribir en una ruta no declarada, el comando falla inmediatamente.

Las únicas escrituras permitidas son:

```text
/tmp
volumen raw
volumen processed
volumen analytics
```

## 5. `/tmp` como tmpfs

La opción utilizada es:

```bash
--tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1777
```

Significa:

| Opción | Efecto |
|---|---|
| `rw` | permite archivos temporales |
| `noexec` | evita ejecutar directamente binarios desde ese mount |
| `nosuid` | ignora bits setuid/setgid |
| `size=64m` | limita el uso de memoria del tmpfs |
| `mode=1777` | permite temporales por usuario con sticky bit |

Los directorios XDG de caché y configuración apuntan a `/tmp`:

```text
XDG_CACHE_HOME=/tmp/.cache
XDG_CONFIG_HOME=/tmp/.config
```

## 6. Capacidades Linux

Docker puede conceder capacidades separadas de UID `0`. La aplicación no necesita ninguna.

```bash
--cap-drop ALL
```

Esto elimina capacidades como:

```text
cambiar propietario de archivos
ignorar ciertos permisos
administrar interfaces de red
crear sockets raw
cargar módulos o cambiar parámetros del kernel
```

La conectividad normal de cliente hacia PostgreSQL sigue funcionando sin capabilities.

## 7. `no-new-privileges`

```bash
--security-opt no-new-privileges:true
```

El kernel impide que el proceso o sus descendientes obtengan privilegios adicionales mediante metadatos de ejecutables.

La imagen también elimina los bits setuid/setgid de archivos regulares bajo:

```text
/usr
/bin
/sbin
```

Son dos capas complementarias.

## 8. Límite de procesos

```bash
--pids-limit 256
```

Esto limita la cantidad de procesos que puede crear el contenedor. Reduce el impacto de errores de recursión, forks accidentales o intentos simples de agotar procesos.

No es una medición de capacidad productiva; es una política adecuada para una CLI de un solo flujo.

## 9. Aplicación y herramientas de build

La imagen es multi-stage.

```text
builder
├── crea virtualenv
├── instala la aplicación
└── elimina pip, setuptools y wheel

runtime
├── recibe solo el virtualenv instalado
├── conserva datos de muestra y SQL
├── elimina ensurepip y site-packages global
└── ejecuta como UID 10001
```

La imagen final no contiene el gestor de paquetes estándar utilizado durante la construcción.

## 10. Volúmenes escribibles

Un bind mount debe permitir escritura al UID `10001`.

Demostración rápida:

```bash
mkdir -p runtime/raw
chmod 0777 runtime/raw
```

Configuración más adecuada en Linux:

```bash
sudo chown 10001:10001 runtime/raw
chmod 0750 runtime/raw
```

Luego:

```bash
docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1777 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 256 \
  --mount type=bind,src="$(pwd)/runtime/raw",dst=/app/data/raw \
  clinical-data-platform:local \
  raw-capture patients /app/data/sample/patients.csv \
  --raw-root /app/data/raw
```

CI comprueba que el recibo generado pertenece realmente al UID `10001`.

## 11. Compose

El servicio `app` declara:

```yaml
user: "10001:10001"
read_only: true
cap_drop:
  - ALL
security_opt:
  - no-new-privileges:true
pids_limit: 256
tmpfs:
  - /tmp:rw,noexec,nosuid,size=64m,mode=1777
```

Los outputs se guardan en volúmenes nombrados:

```text
app_raw
app_processed
app_analytics
```

Esto evita depender del propietario de una carpeta del host.

## 12. Qué valida CI

La prueba de referencia confirma:

```text
Config.User == 10001:10001
id -u == 10001
id -g == 10001
shell == /usr/sbin/nologin
/app no es escribible
/opt/venv no es escribible
/tmp sí es escribible
contratos funcionan
perfiles Synthea funcionan
PostgreSQL funciona
raw capture funciona
receipts pertenecen al UID 10001
```

Además, pruebas de política inspeccionan Dockerfile, Compose y CI para impedir que estas restricciones desaparezcan silenciosamente.

## 13. Comando de referencia

```bash
docker build --tag clinical-data-platform:local .

docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1777 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 256 \
  clinical-data-platform:local validate-contracts
```

## 14. Qué no demuestra

Este hito no demuestra:

```text
ausencia de container escapes
seguridad del kernel del host
seguridad de la red
manejo seguro de secretos
firma o procedencia de imágenes
cumplimiento regulatorio
preparación para PHI
seguridad clínica
```

## 15. Explicación profesional defendible

> La imagen ejecuta la aplicación como UID/GID fijo 10001, con cuenta sin login. El runtime se valida con filesystem raíz de solo lectura, todas las capabilities eliminadas, `no-new-privileges`, tmpfs `noexec,nosuid` y límite de procesos. Los directorios de aplicación son inmutables y las escrituras requieren volúmenes explícitos. CI ejecuta contratos, PostgreSQL y raw capture bajo esas restricciones y verifica que los archivos resultantes pertenecen al usuario no root. Esto reduce el impacto de una vulnerabilidad, pero no sustituye controles del host, red, secretos, firma de imágenes ni cumplimiento regulatorio.

## 16. Preguntas que debes poder responder

1. ¿Por qué `root` dentro de un contenedor sigue siendo una superficie de riesgo?
2. ¿Por qué no basta con añadir `USER` al Dockerfile?
3. ¿Qué diferencia existe entre UID, GID y nombre de usuario?
4. ¿Qué ocurre con un bind mount que no permite escritura al UID `10001`?
5. ¿Qué protege `--read-only`?
6. ¿Por qué `/tmp` se monta como tmpfs?
7. ¿Qué hacen `noexec` y `nosuid`?
8. ¿Qué son las Linux capabilities?
9. ¿Qué añade `no-new-privileges`?
10. ¿Por qué se verifica el propietario de los receipts creados?
11. ¿Qué ventaja tienen los named volumes frente a bind mounts en este caso?
12. ¿Qué riesgos permanecen fuera del alcance de este hito?
