import argparse
import os
from datetime import date, datetime, timedelta, timezone

from backend.db import database_url


DEMO_SLUG = "barberia-cauce-norte-demo"
DEMO_NAME = "Barbería Cauce Norte — DEMO"
BACKUP_TABLES = (
    "locales",
    "usuarios",
    "usuario_roles",
    "profesionales",
    "servicios",
    "profesional_servicios",
    "disponibilidad_semanal",
    "estados_panel_local",
)

PROFESSIONALS = (
    {
        "name": "Mateo Ríos",
        "email": "mateo.rios.demo@kauze.cl",
        "specialty": "Barbero senior",
        "color": "#2563EB",
    },
    {
        "name": "Camila Soto",
        "email": "camila.soto.demo@kauze.cl",
        "specialty": "Especialista en fade",
        "color": "#0EA5E9",
    },
    {
        "name": "Diego Mena",
        "email": "diego.mena.demo@kauze.cl",
        "specialty": "Barbero y grooming",
        "color": "#14B8A6",
    },
)

SERVICES = (
    {
        "name": "Corte clásico",
        "slug": "corte-clasico",
        "duration": 45,
        "price": 15000,
    },
    {"name": "Fade", "slug": "fade", "duration": 60, "price": 18000},
    {
        "name": "Perfilado de barba",
        "slug": "perfilado-barba",
        "duration": 30,
        "price": 10000,
    },
    {
        "name": "Corte + barba",
        "slug": "corte-barba",
        "duration": 75,
        "price": 24000,
    },
)


def build_panel_state(today=None):
    today = today or date.today()
    tomorrow = today + timedelta(days=1)
    following = today + timedelta(days=2)
    later = today + timedelta(days=3)

    professionals = [
        {
            "id": f"demo-pro-{index}",
            "name": item["name"],
            "role": item["specialty"],
            "note": "Perfil ficticio para pruebas internas.",
            "commission": 45,
            "days": ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"],
            "shifts": ["10:00 - 20:00"],
            "services": [service["name"] for service in SERVICES],
        }
        for index, item in enumerate(PROFESSIONALS, start=1)
    ]
    services = [
        {
            "id": f"demo-ser-{index}",
            "name": item["name"],
            "duration": f'{item["duration"]} min',
            "price": item["price"],
            "professional": "Todos",
        }
        for index, item in enumerate(SERVICES, start=1)
    ]

    return {
        "name": DEMO_NAME,
        "type": "barberia",
        "demoMode": True,
        "externalMessagingEnabled": False,
        "ownerWhatsapp": "",
        "ownerCalendarEmail": "",
        "depositEnabled": False,
        "depositMode": "none",
        "depositPercent": 0,
        "depositFixedAmount": 0,
        "depositMinimum": 0,
        "activeTheme": "Kauze Base",
        "pageTitle": "Reserva tu próxima hora en Cauce Norte",
        "pageSubtitle": "Perfil ficticio de KAUZE para comprobar agenda, servicios y operación.",
        "pageCta": "Reservar hora DEMO",
        "bannerStyle": "soft",
        "bannerImage": "",
        "businessStatus": "DISPONIBLE",
        "notificationPreferences": {
            "frequency": "daily",
            "delivery": "panel_only",
            "externalDeliveryEnabled": False,
        },
        "professionals": {"barberia": professionals},
        "services": {"barberia": services},
        "clients": {
            "barberia": [
                {
                    "id": "demo-cli-1",
                    "name": "Renata Silva",
                    "phone": "Sin teléfono — DEMO",
                    "lastService": "Corte clásico",
                    "nextAction": "Simular recordatorio interno",
                    "totalBilling": 45000,
                    "stars": 5,
                },
                {
                    "id": "demo-cli-2",
                    "name": "Tomás Vega",
                    "phone": "Sin teléfono — DEMO",
                    "lastService": "Fade",
                    "nextAction": "Confirmar asistencia en panel",
                    "totalBilling": 36000,
                    "stars": 4,
                },
                {
                    "id": "demo-cli-3",
                    "name": "Natalia León",
                    "phone": "Sin teléfono — DEMO",
                    "lastService": "Corte + barba",
                    "nextAction": "Simular fidelización",
                    "totalBilling": 72000,
                    "stars": 5,
                },
            ]
        },
        "appointments": {
            "barberia": [
                {
                    "id": "demo-appt-1",
                    "date": tomorrow.isoformat(),
                    "time": "10:00",
                    "client": "Renata Silva",
                    "service": "Corte clásico",
                    "professional": "Mateo Ríos",
                    "status": "Confirmada",
                    "source": "cliente",
                    "confirmationStatus": "Confirmada",
                    "paymentStatus": "Sin abono",
                    "notifications": [],
                },
                {
                    "id": "demo-appt-2",
                    "date": tomorrow.isoformat(),
                    "time": "11:30",
                    "client": "Tomás Vega",
                    "service": "Fade",
                    "professional": "Camila Soto",
                    "status": "Pendiente",
                    "source": "cliente",
                    "confirmationStatus": "Pendiente",
                    "paymentStatus": "Sin abono",
                    "notifications": [],
                },
                {
                    "id": "demo-appt-3",
                    "date": following.isoformat(),
                    "time": "16:00",
                    "client": "Natalia León",
                    "service": "Corte + barba",
                    "professional": "Diego Mena",
                    "status": "Confirmada",
                    "source": "panel",
                    "notifications": [],
                },
                {
                    "id": "demo-appt-4",
                    "date": later.isoformat(),
                    "time": "13:00",
                    "client": "Sebastián Mora",
                    "service": "Perfilado de barba",
                    "professional": "Mateo Ríos",
                    "status": "Cancelada",
                    "source": "panel",
                    "notifications": [],
                },
            ]
        },
        "campaigns": {
            "barberia": [
                {
                    "id": "demo-campaign-1",
                    "title": "Horas tranquilas — DEMO",
                    "description": "Campaña simulada; no envía mensajes externos.",
                    "type": "campaign",
                    "status": "Borrador",
                    "channel": "Simulación interna",
                }
            ]
        },
        "virtualQueue": [
            {
                "id": "demo-queue-1",
                "name": "Cliente Walk-In 01",
                "status": "waiting",
                "estimatedMinutes": 25,
                "externalMessagingEnabled": False,
            },
            {
                "id": "demo-queue-2",
                "name": "Cliente Walk-In 02",
                "status": "confirmation_pending",
                "estimatedMinutes": 40,
                "externalMessagingEnabled": False,
            },
        ],
    }


def create_backup(conn):
    from psycopg import sql

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    schema_name = f"kauze_backup_demo_{timestamp}"
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    for table_name in BACKUP_TABLES:
        conn.execute(
            sql.SQL("CREATE TABLE {}.{} AS TABLE public.{}").format(
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
                sql.Identifier(table_name),
            )
        )
    return schema_name


def upsert_demo(conn, owner_email):
    from psycopg.types.json import Jsonb

    category_id = conn.execute(
        "SELECT id FROM categorias WHERE slug = 'barberia' AND activo = TRUE"
    ).fetchone()[0]
    owner = conn.execute(
        "SELECT id FROM usuarios WHERE LOWER(email) = %s AND estado = 'activo'",
        (owner_email.lower(),),
    ).fetchone()
    if not owner:
        raise RuntimeError(f"No existe una cuenta activa para {owner_email}.")
    owner_id = owner[0]

    local_id = conn.execute(
        """
        INSERT INTO locales (
          categoria_id, nombre, slug, descripcion, direccion, comuna, ciudad,
          telefono_whatsapp, email_contacto, tema_visual, estado,
          requiere_abono, tipo_abono, porcentaje_abono,
          monto_abono_fijo, monto_abono_minimo
        )
        VALUES (
          %s, %s, %s, %s, %s, %s, %s,
          NULL, %s, 'Kauze Base', 'activo', FALSE, 'none', 0, 0, 0
        )
        ON CONFLICT (slug) DO UPDATE
        SET nombre = EXCLUDED.nombre,
            categoria_id = EXCLUDED.categoria_id,
            descripcion = EXCLUDED.descripcion,
            direccion = EXCLUDED.direccion,
            comuna = EXCLUDED.comuna,
            ciudad = EXCLUDED.ciudad,
            telefono_whatsapp = NULL,
            email_contacto = EXCLUDED.email_contacto,
            tema_visual = EXCLUDED.tema_visual,
            estado = 'activo',
            requiere_abono = FALSE,
            tipo_abono = 'none',
            porcentaje_abono = 0,
            monto_abono_fijo = 0,
            monto_abono_minimo = 0
        RETURNING id
        """,
        (
            category_id,
            DEMO_NAME,
            DEMO_SLUG,
            "Negocio totalmente ficticio para pruebas internas de KAUZE.",
            "Avenida Demo 123",
            "Providencia",
            "Santiago",
            "demo.cauce-norte@kauze.cl",
        ),
    ).fetchone()[0]

    owner_role_id = conn.execute(
        "SELECT id FROM roles WHERE slug = 'dueno' AND activo = TRUE"
    ).fetchone()[0]
    professional_role_id = conn.execute(
        "SELECT id FROM roles WHERE slug = 'profesional' AND activo = TRUE"
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO usuario_roles (usuario_id, rol_id, local_id, otorgado_por)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (usuario_id, rol_id, local_id) WHERE local_id IS NOT NULL
        DO NOTHING
        """,
        (owner_id, owner_role_id, local_id, owner_id),
    )

    professional_ids = []
    for item in PROFESSIONALS:
        user_id = conn.execute(
            """
            INSERT INTO usuarios (nombre_completo, email, estado)
            VALUES (%s, %s, 'activo')
            ON CONFLICT (LOWER(email)) WHERE email IS NOT NULL DO UPDATE
            SET nombre_completo = EXCLUDED.nombre_completo,
                estado = 'activo',
                actualizado_en = NOW()
            RETURNING id
            """,
            (item["name"], item["email"]),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO usuario_roles (usuario_id, rol_id, local_id, otorgado_por)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (usuario_id, rol_id, local_id) WHERE local_id IS NOT NULL
            DO NOTHING
            """,
            (user_id, professional_role_id, local_id, owner_id),
        )
        professional_id = conn.execute(
            """
            INSERT INTO profesionales (
              local_id, usuario_id, nombre_publico, especialidad, biografia,
              color_agenda, acepta_reservas, estado
            )
            VALUES (%s, %s, %s, %s, %s, %s, TRUE, 'activo')
            ON CONFLICT (local_id, usuario_id) DO UPDATE
            SET nombre_publico = EXCLUDED.nombre_publico,
                especialidad = EXCLUDED.especialidad,
                biografia = EXCLUDED.biografia,
                color_agenda = EXCLUDED.color_agenda,
                acepta_reservas = TRUE,
                estado = 'activo',
                actualizado_en = NOW()
            RETURNING id
            """,
            (
                local_id,
                user_id,
                item["name"],
                item["specialty"],
                "Perfil ficticio para pruebas internas. Sin mensajería externa.",
                item["color"],
            ),
        ).fetchone()[0]
        professional_ids.append(professional_id)

    service_ids = []
    for item in SERVICES:
        service_id = conn.execute(
            """
            INSERT INTO servicios (
              local_id, nombre, slug, descripcion, duracion_minutos, precio_clp, activo
            )
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (local_id, slug) DO UPDATE
            SET nombre = EXCLUDED.nombre,
                descripcion = EXCLUDED.descripcion,
                duracion_minutos = EXCLUDED.duracion_minutos,
                precio_clp = EXCLUDED.precio_clp,
                activo = TRUE,
                actualizado_en = NOW()
            RETURNING id
            """,
            (
                local_id,
                item["name"],
                item["slug"],
                "Servicio ficticio para pruebas internas.",
                item["duration"],
                item["price"],
            ),
        ).fetchone()[0]
        service_ids.append(service_id)

    for professional_id in professional_ids:
        for service_id in service_ids:
            conn.execute(
                """
                INSERT INTO profesional_servicios (
                  local_id, profesional_id, servicio_id, activo
                )
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (profesional_id, servicio_id) DO UPDATE
                SET activo = TRUE, actualizado_en = NOW()
                """,
                (local_id, professional_id, service_id),
            )

    conn.execute(
        "DELETE FROM disponibilidad_semanal WHERE local_id = %s", (local_id,)
    )
    for professional_id in professional_ids:
        for weekday in range(1, 7):
            conn.execute(
                """
                INSERT INTO disponibilidad_semanal (
                  local_id, profesional_id, dia_semana, hora_inicio, hora_fin,
                  vigente_desde, activo
                )
                VALUES (%s, %s, %s, '10:00', '20:00', CURRENT_DATE, TRUE)
                """,
                (local_id, professional_id, weekday),
            )

    panel_state = build_panel_state()
    conn.execute(
        """
        INSERT INTO estados_panel_local (local_id, estado, actualizado_por)
        VALUES (%s, %s, %s)
        ON CONFLICT (local_id) DO UPDATE
        SET estado = EXCLUDED.estado,
            actualizado_por = EXCLUDED.actualizado_por,
            actualizado_en = NOW(),
            version = estados_panel_local.version + 1
        """,
        (local_id, Jsonb(panel_state), owner_id),
    )
    return {
        "local_id": str(local_id),
        "slug": DEMO_SLUG,
        "name": DEMO_NAME,
        "professionals": len(professional_ids),
        "services": len(service_ids),
        "appointments": len(panel_state["appointments"]["barberia"]),
        "external_messaging": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Crea el negocio ficticio de KAUZE.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica el respaldo y el seed. Sin esta opción solo muestra el preview.",
    )
    args = parser.parse_args()

    if not args.apply:
        preview = build_panel_state(date(2026, 7, 17))
        print(f"Preview: {DEMO_NAME} ({DEMO_SLUG})")
        print(f"Profesionales: {len(preview['professionals']['barberia'])}")
        print(f"Servicios: {len(preview['services']['barberia'])}")
        print(f"Reservas: {len(preview['appointments']['barberia'])}")
        print("Mensajería externa: desactivada")
        return

    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL no está configurada.")
    owner_email = os.environ.get(
        "KAUZE_DEMO_OWNER_EMAIL",
        os.environ.get("KAUZE_BOOTSTRAP_EMAIL", ""),
    ).strip().lower()
    if not owner_email:
        raise RuntimeError("Falta KAUZE_DEMO_OWNER_EMAIL o KAUZE_BOOTSTRAP_EMAIL.")

    import psycopg

    with psycopg.connect(url) as conn:
        backup_schema = create_backup(conn)
        result = upsert_demo(conn, owner_email)
        conn.commit()

    print(f"Respaldo creado: {backup_schema}")
    print(f"Negocio DEMO listo: {result['slug']}")
    print(
        "Datos: "
        f"{result['professionals']} profesionales, "
        f"{result['services']} servicios, "
        f"{result['appointments']} reservas."
    )
    print("Mensajería externa: desactivada")


if __name__ == "__main__":
    main()
