from rest_framework import serializers
from .models import Usuario, Medico, Agendamento


class UsuarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ['id', 'first_name', 'last_name', 'username',
                  'tipo', 'email', 'telefone', 'password']

        extra_kwargs = {
            'password': {'write_only': True}
        }

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = Usuario(**validated_data)
        user.set_password(password)
        user.save()
        return user


class MedicoSerializer(serializers.ModelSerializer):
    # Campos calculados (Só leitura - buscam dados da tabela Usuario)
    nome = serializers.CharField(source='usuario.get_full_name', read_only=True)
    email = serializers.EmailField(source='usuario.email', read_only=True)
    telefone = serializers.CharField(source='usuario.telefone', read_only=True)

    class Meta:
        model = Medico
        fields = ['id', 'usuario', 'nome', 'especialidade', 'crm', 'email', 'telefone', 'disponibilidade', 'ativo']


class AgendamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agendamento
        fields = ['id', 'medico', 'paciente',
                  'data_horario', 'status', 'criado_em']
        read_only_fields = ['paciente', 'criado_em']
