# Arquitectura aprobada de usuarios y negocios

## Quién inicia sesión

Solo existen dos tipos de personas autenticadas en esta etapa:

1. **SuperAdmin de Kauze**, para operación interna.
2. **Dueño de negocio**, que ingresará con Google y administrará uno o más negocios autorizados.

Los trabajadores y clientes no reciben contraseñas ni acceso al panel del negocio.

## Cómo se relacionan los datos

```text
Usuario dueño (Google)
        |
        +-- UsuarioRol: Dueño
                |
                +-- Negocio / local
                      |-- Suscripción SaaS
                      |-- Servicios
                      |-- Profesionales internos
                      |-- Clientes operativos
                      `-- Reservas
```

## Trabajadores

Cada trabajador es una ficha interna del negocio. El dueño configura:

- nombre;
- foto opcional;
- especialidad;
- servicios que presta;
- horario y bloqueos;
- comisión porcentual, fija o desactivada.

Una ficha de trabajador no tiene correo de acceso, contraseña ni sesión.

## Clientes

El cliente reserva sin Google y sin crear una cuenta. La reserva crea o reutiliza
un registro de cliente dentro del negocio usando teléfono o correo.

Más adelante, el cliente podrá consultar su historial transversal mediante un
código temporal enviado por WhatsApp. Ese acceso será opcional y no convertirá
al cliente en usuario del panel.

## Seguridad multi-negocio

Todas las tablas operativas incluyen `local_id`. Las relaciones usan claves
compuestas para impedir que una reserva de un negocio apunte a un cliente,
servicio o profesional de otro. PostgreSQL incorpora además políticas RLS que
solo permiten operar con el `local_id` fijado por el backend en la transacción.

## Transición segura

Las columnas antiguas de suscripción y los vínculos históricos entre usuarios y
profesionales se conservan temporalmente para no romper la demo. Los nuevos
registros ya deben utilizar el modelo definitivo y las columnas antiguas se
eliminarán únicamente cuando Admin y producción hayan migrado por completo.
