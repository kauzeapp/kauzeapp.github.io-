import { Appointment, Business, DemoState } from '../types';

export const businesses: Business[] = [
  {
    id: 'corte-fino',
    name: 'Barbería Corte Fino',
    category: 'barberia',
    location: 'Providencia, Santiago',
    rating: 4.9,
    services: [
      { id: 'corte-clasico', name: 'Corte clásico', durationMinutes: 45, priceClp: 15000 },
      { id: 'corte-barba', name: 'Corte + barba', durationMinutes: 75, priceClp: 23000 },
    ],
    professionals: [
      { id: 'matias', name: 'Matías Soto', specialty: 'Fade y barba' },
      { id: 'diego', name: 'Diego Rojas', specialty: 'Corte clásico' },
    ],
  },
  {
    id: 'norte-fade',
    name: 'Norte Fade Club',
    category: 'barberia',
    location: 'Huechuraba, Santiago',
    rating: 4.8,
    services: [
      { id: 'fade', name: 'Fade premium', durationMinutes: 60, priceClp: 18000 },
      { id: 'barba', name: 'Perfilado de barba', durationMinutes: 30, priceClp: 10000 },
    ],
    professionals: [{ id: 'benjamin', name: 'Benjamín Díaz', specialty: 'Fade premium' }],
  },
  {
    id: 'nails-valentina',
    name: 'Studio Nails Valentina',
    category: 'manicure',
    location: 'Ñuñoa, Santiago',
    rating: 4.9,
    services: [
      { id: 'esmaltado', name: 'Esmaltado permanente', durationMinutes: 60, priceClp: 22000 },
      { id: 'soft-gel', name: 'Extensión Soft Gel', durationMinutes: 120, priceClp: 35000 },
    ],
    professionals: [{ id: 'valentina', name: 'Valentina Pérez', specialty: 'Nail art' }],
  },
  {
    id: 'lash-camila',
    name: 'Lash Room Camila',
    category: 'pestanas',
    location: 'Las Condes, Santiago',
    rating: 5,
    services: [
      { id: 'lifting', name: 'Lifting de pestañas', durationMinutes: 75, priceClp: 28000 },
      { id: 'clasicas', name: 'Extensiones clásicas', durationMinutes: 120, priceClp: 39000 },
    ],
    professionals: [{ id: 'camila', name: 'Camila Muñoz', specialty: 'Lifting y extensiones' }],
  },
  {
    id: 'glow',
    name: 'Estética Glow',
    category: 'estetica',
    location: 'Vitacura, Santiago',
    rating: 4.7,
    services: [
      { id: 'limpieza', name: 'Limpieza facial', durationMinutes: 60, priceClp: 32000 },
      { id: 'masaje', name: 'Masaje relajante', durationMinutes: 60, priceClp: 35000 },
    ],
    professionals: [{ id: 'fernanda', name: 'Fernanda Silva', specialty: 'Cuidado facial' }],
  },
  {
    id: 'peluqueria-studio',
    name: 'Peluquería Studio',
    category: 'peluqueria',
    location: 'La Reina, Santiago',
    rating: 4.8,
    services: [
      { id: 'corte-dama', name: 'Corte y brushing', durationMinutes: 75, priceClp: 27000 },
      { id: 'color', name: 'Coloración', durationMinutes: 150, priceClp: 55000 },
    ],
    professionals: [{ id: 'paula', name: 'Paula Torres', specialty: 'Color y styling' }],
  },
];

const todayAt = (hours: number, minutes: number) => {
  const date = new Date();
  date.setHours(hours, minutes, 0, 0);
  return date.toISOString();
};

export const initialAppointments: Appointment[] = [
  {
    id: 'demo-1',
    businessId: 'corte-fino',
    clientName: 'Sofía Martínez',
    clientPhone: '+56912345678',
    serviceId: 'corte-clasico',
    professionalId: 'matias',
    startsAt: todayAt(10, 30),
    priceClp: 15000,
    status: 'Confirmada',
    paymentStatus: 'Pagado demo',
  },
  {
    id: 'demo-2',
    businessId: 'corte-fino',
    clientName: 'Nicolás Herrera',
    clientPhone: '+56987654321',
    serviceId: 'corte-barba',
    professionalId: 'diego',
    startsAt: todayAt(12, 0),
    priceClp: 23000,
    status: 'Esperando confirmación',
    paymentStatus: 'Sin abono',
  },
];

export const initialDemoState: DemoState = {
  appointments: initialAppointments,
  businessStatus: 'Disponible',
  depositEnabled: true,
  depositPercent: 30,
};

export const availableSlots = ['09:30', '11:00', '12:30', '15:00', '16:30', '18:00'];

export const categoryLabels = {
  barberia: 'Barbería',
  manicure: 'Manicure',
  pestanas: 'Pestañas',
  estetica: 'Estética',
  peluqueria: 'Peluquería',
} as const;
