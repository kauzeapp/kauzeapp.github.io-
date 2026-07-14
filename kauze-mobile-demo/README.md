# Kauze Mobile Demo

Demo móvil de Kauze construida con Expo, React Native y TypeScript.

## Alcance actual

- Selector de experiencia: Cliente, Dueño/Encargado, Profesional y Admin Kauze.
- Exploración de negocios asociados por rubro y ubicación.
- Flujo local de reserva con servicio, profesional, hora y abono simulado.
- Vista de citas con confirmación y cancelación demo.
- Panel empresa con agenda, estado del negocio y configuración de abono.
- Panel profesional con Comenzar, Terminar y No asistió.
- Panel admin con métricas, negocios demo y programa fundador.
- Persistencia local mediante AsyncStorage.

No existen pagos, mensajes, cuentas ni datos personales reales.

## Probar gratis con Expo Go

Requisitos:

- Node.js 20.19 o superior.
- Aplicación Expo Go instalada en el teléfono.

```bash
cd kauze-mobile-demo
npm install
npx expo start
```

Escanea el código QR con Expo Go. Si el teléfono y el computador no pueden verse en la misma red:

```bash
npx expo start --tunnel
```

## Datos locales

La demo guarda su estado en:

```text
kauzeMobileDemoStateV1
```

Este almacenamiento no es seguro para credenciales ni datos sensibles. Solo contiene información mock de la demostración.

## Arquitectura futura

La app móvil y los portales web deben consumir la misma API HTTPS:

```text
Landing / Paneles web ─┐
                      ├── API Kauze (FastAPI) ── PostgreSQL
App Android / iOS ────┘
```

PostgreSQL nunca debe exponerse directamente a la app o al navegador. La futura implementación comienza en `src/services/api.ts`.

## Preparación para Google Play

El proyecto reserva el identificador Android:

```text
cl.kauze.app
```

Antes de publicar se necesitará:

1. Backend y autenticación reales.
2. Política de privacidad y términos.
3. Eliminación de cuenta y tratamiento de datos personales.
4. Icono, splash y capturas finales.
5. Pruebas internas y manejo de errores.
6. Firma Android y cuenta de Google Play Console.
7. Compilación AAB de producción con EAS Build.

`eas.json` ya incluye perfiles para APK interno y AAB de producción, pero no se debe enviar a la tienda hasta completar seguridad, privacidad y pruebas.
