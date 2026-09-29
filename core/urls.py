from django.urls import path
from . import views

urlpatterns = [
    path('equipo/', views.equipo, name='equipo'),
    path('empresa/elegir/', views.elegir_empresa, name='elegir_empresa'),
    path('entregas/', views.entregas, name='entregas'),
    path('entregas/<int:mensaje_id>/reintentar/', views.reintentar_entrega, name='reintentar_entrega'),
    path('bot/simulador/', views.simulador, name='simulador'),
    path('bot/exportar/', views.descargar_flujo, name='descargar_flujo'),
    path('bot/importar/', views.cargar_flujo, name='cargar_flujo'),
    path('bot/nodos/<int:nodo_id>/duplicar/', views.duplicar_nodo, name='duplicar_nodo'),
    path('whatsapp/diagnostico/', views.diagnostico_whatsapp, name='diagnostico_whatsapp'),
    path('atencion/<int:sesion_id>/tomar/', views.tomar_conversacion, name='tomar_conversacion'),
    # pantallas y acciones que usa cada cliente en su panel
    path('metricas/', views.metricas, name='metricas'),
    path('perfil/', views.perfil, name='perfil'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('whatsapp/conectar/', views.conectar_whatsapp, name='conectar_whatsapp'),
    path('whatsapp/desconectar/', views.desconectar_whatsapp, name='desconectar_whatsapp'),
    path('whatsapp/estado/', views.estado_whatsapp, name='estado_whatsapp'),
    path('bot/opciones/<int:opcion_id>/pdf/', views.archivo_opcion, name='archivo_opcion'),
    path('bot/configurar/', views.configuracion_bot, name='configuracion_bot'),
    path('bot/nodos/crear/', views.guardar_nodo, name='crear_nodo'),
    path('bot/nodos/<int:nodo_id>/guardar/', views.guardar_nodo, name='guardar_nodo'),
    path('bot/nodos/<int:nodo_id>/eliminar/', views.eliminar_nodo, name='eliminar_nodo'),
    path('bot/nodos/<int:nodo_id>/opciones/crear/', views.guardar_opcion, name='crear_opcion'),
    path('bot/nodos/<int:nodo_id>/opciones/<int:opcion_id>/guardar/', views.guardar_opcion, name='guardar_opcion'),
    path('bot/nodos/<int:nodo_id>/opciones/<int:opcion_id>/eliminar/', views.eliminar_opcion, name='eliminar_opcion'),
    path('atencion/', views.atencion_humana, name='atencion_humana'),
    path('atencion/<int:sesion_id>/responder/', views.responder_agente, name='responder_agente'),
    path('atencion/<int:sesion_id>/<str:estado>/', views.cambiar_estado_conversacion, name='cambiar_estado_conversacion'),
    # estas rutas internas son para la comunicacion con node
    path('interno/whatsapp/evento/', views.evento_whatsapp_interno, name='evento_whatsapp_interno'),
    path('interno/whatsapp/sesiones/', views.sesiones_whatsapp_internas, name='sesiones_whatsapp_internas'),
    path('interno/whatsapp/<uuid:identificador>/opciones/<int:opcion_id>/pdf/', views.archivo_opcion_interno, name='archivo_opcion_interno'),
]
