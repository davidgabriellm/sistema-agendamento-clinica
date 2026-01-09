from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UsuarioViewSet, MedicoViewSet, AgendamentoViewSet

router = DefaultRouter()

router.register(r'usuarios', UsuarioViewSet)
router.register(r'medicos', MedicoViewSet)
router.register(r'agendamentos', AgendamentoViewSet)

urlpatterns = [
    path('', include(router.urls)),
]