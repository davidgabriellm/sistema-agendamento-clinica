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
    class Meta:
        model = Medico
        fields = ['id', 'nome', 'especialidade', 'crm',
                  'telefone', 'email', 'disponibilidade']


class AgendamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agendamento
        fields = ['id', 'medico', 'paciente',
                  'data_horario', 'status', 'criado_em']
        read_only_fields = ['paciente', 'criado_em']
