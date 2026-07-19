from datetime import time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from api.models import (
    Agendamento,
    BloqueioAgendaClinica,
    Clinica,
    ConviteCadastroPaciente,
    Dentista,
    HorarioFuncionamentoClinica,
    IndisponibilidadeDentista,
    Procedimento,
    Usuario,
)


def criar_usuario(username, cpf, email, password='SenhaAtual123!', tipo='PACIENTE', **extra):
    dados = {
        'username': username,
        'password': password,
        'tipo': tipo,
        'nome_completo': extra.pop('nome_completo', f'Usuario {username}'),
        'email': email,
        'cpf': cpf,
        'data_nascimento': extra.pop('data_nascimento', '1990-01-01'),
        'telefone': extra.pop('telefone', '82999999999'),
    }
    dados.update(extra)
    return Usuario.objects.create_user(**dados)


def criar_expediente(clinica, inicio=time(0, 0), fim=time(23, 59), dias=range(7)):
    for dia_semana in dias:
        HorarioFuncionamentoClinica.objects.get_or_create(
            clinica=clinica,
            dia_semana=dia_semana,
            horario_inicio=inicio,
            horario_fim=fim,
            defaults={'ativo': True},
        )


def data_local_futura(clinica, dias=30, hora=10, minuto=0, dia_semana=None):
    timezone_clinica = ZoneInfo(clinica.timezone)
    data_local = timezone.localtime(timezone.now(), timezone_clinica) + timedelta(days=dias)
    data_local = data_local.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    while data_local <= timezone.localtime(timezone.now(), timezone_clinica):
        data_local += timedelta(days=1)
    if dia_semana is not None:
        while data_local.weekday() != dia_semana:
            data_local += timedelta(days=1)
    return data_local


class DentistaViewSetTest(APITestCase):
    def setUp(self):
        self.clinica = Clinica.objects.create(nome='Clinica Teste')
        self.paciente = criar_usuario(
            username='paciente_teste',
            cpf='10000000001',
            email='paciente@example.com',
            clinica=self.clinica,
        )
        self.user_dentista = criar_usuario(
            username='dentista_teste',
            cpf='10000000002',
            email='dentista@example.com',
            nome_completo='Ana Silva',
            tipo='DENTISTA',
            clinica=self.clinica,
        )
        Dentista.objects.create(
            clinica=self.clinica,
            usuario=self.user_dentista,
            especialidade='Odontopediatria',
            cro='98765-AL',
        )
        self.url = reverse('dentista-list')

    def test_listar_dentistas_sem_token_retorna_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_listar_dentistas_com_token_retorna_200(self):
        self.client.force_authenticate(user=self.paciente)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['especialidade'], 'Odontopediatria')

    def test_endpoint_versionado_dentistas_usa_contrato_odontologico(self):
        self.client.force_authenticate(user=self.paciente)
        response = self.client.get('/api/v1/dentistas/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertIn('cro', response.data['results'][0])
        self.assertNotIn('crm', response.data['results'][0])

    def test_endpoint_legacy_medicos_nao_existe_no_v1(self):
        self.client.force_authenticate(user=self.paciente)
        response = self.client.get('/api/v1/medicos/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class UsuarioCadastroViewSetTest(APITestCase):
    def setUp(self):
        self.lista_url = reverse('usuario-list')

    def payload_cadastro(self, **overrides):
        payload = {
            'username': 'novo_usuario',
            'password': 'SenhaForte123!',
            'nome_completo': 'Novo Paciente',
            'nome_preferido': '',
            'email': 'novo.paciente@example.com',
            'cpf': '123.456.789-09',
            'data_nascimento': '1995-04-20',
            'telefone': '82988887777',
        }
        payload.update(overrides)
        return payload

    def test_cadastro_publico_cria_paciente_com_dados_padronizados(self):
        response = self.client.post(self.lista_url, self.payload_cadastro(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        usuario = Usuario.objects.get(username='novo_usuario')
        self.assertEqual(usuario.tipo, 'PACIENTE')
        self.assertEqual(usuario.nome_completo, 'Novo Paciente')
        self.assertEqual(usuario.nome_preferido, '')
        self.assertEqual(usuario.email, 'novo.paciente@example.com')
        self.assertEqual(usuario.cpf, '12345678909')
        self.assertEqual(usuario.telefone, '82988887777')
        self.assertNotIn('password', response.data)
        self.assertNotIn('tipo', response.data)

    def test_cadastro_publico_nao_permite_criar_admin(self):
        response = self.client.post(self.lista_url, self.payload_cadastro(tipo='ADMIN'), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        usuario = Usuario.objects.get(username='novo_usuario')
        self.assertEqual(usuario.tipo, 'PACIENTE')

    def test_cpf_duplicado_deve_ser_rejeitado(self):
        criar_usuario('existente', '12345678909', 'existente@example.com')

        response = self.client.post(self.lista_url, self.payload_cadastro(), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cpf', response.data)

    def test_email_duplicado_deve_ser_rejeitado(self):
        criar_usuario('existente', '99999999999', 'novo.paciente@example.com')

        response = self.client.post(self.lista_url, self.payload_cadastro(), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.data)

    def test_telefone_obrigatorio_deve_ser_validado(self):
        response = self.client.post(self.lista_url, self.payload_cadastro(telefone=''), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('telefone', response.data)

    def test_endereco_estruturado_e_salvo_e_retornado(self):
        response = self.client.post(
            self.lista_url,
            self.payload_cadastro(
                endereco={
                    'cep': '57000-000',
                    'logradouro': 'Rua das Flores',
                    'numero': '123',
                    'complemento': 'Sala 2',
                    'bairro': 'Centro',
                    'cidade': 'Maceio',
                    'estado': 'AL',
                }
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        usuario = Usuario.objects.get(username='novo_usuario')
        self.assertEqual(usuario.endereco.cidade, 'Maceio')
        self.assertEqual(response.data['endereco']['logradouro'], 'Rua das Flores')
        self.assertEqual(response.data['endereco']['estado'], 'AL')


class UsuarioSegurancaViewSetTest(APITestCase):
    def setUp(self):
        self.clinica = Clinica.objects.create(nome='Clinica A')
        self.outra_clinica = Clinica.objects.create(nome='Clinica B')
        self.usuario = criar_usuario(
            username='paciente_um',
            cpf='20000000001',
            email='paciente.um@example.com',
            nome_completo='Paciente Um',
            clinica=self.clinica,
        )
        self.outro_usuario = criar_usuario(
            username='paciente_dois',
            cpf='20000000002',
            email='paciente.dois@example.com',
            clinica=self.outra_clinica,
        )
        self.admin = criar_usuario(
            username='administrador',
            cpf='20000000003',
            email='admin@example.com',
            tipo='ADMIN',
            is_staff=True,
        )
        self.lista_url = reverse('usuario-list')
        self.detalhe_outro_url = reverse('usuario-detail', args=[self.outro_usuario.pk])
        self.meu_perfil_url = reverse('usuario-detail', args=[self.usuario.pk])
        self.alterar_senha_url = reverse('usuario-alterar-senha')

    def test_usuario_comum_nao_lista_usuarios(self):
        self.client.force_authenticate(self.usuario)
        response = self.client.get(self.lista_url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_usuario_comum_nao_acessa_outro_perfil(self):
        self.client.force_authenticate(self.usuario)
        response = self.client.get(self.detalhe_outro_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_usuario_comum_nao_altera_tipo_cpf_ou_senha_no_endpoint_comum(self):
        senha_original = self.usuario.password
        cpf_original = self.usuario.cpf
        self.client.force_authenticate(self.usuario)
        response = self.client.patch(
            self.meu_perfil_url,
            {
                'nome_preferido': 'Paciente',
                'telefone': '82977776666',
                'tipo': 'ADMIN',
                'clinica': self.outra_clinica.pk,
                'cpf': '30000000000',
                'password': 'TextoPuro123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.tipo, 'PACIENTE')
        self.assertEqual(self.usuario.clinica_id, self.clinica.id)
        self.assertEqual(self.usuario.cpf, cpf_original)
        self.assertEqual(self.usuario.password, senha_original)
        self.assertEqual(self.usuario.telefone, '82977776666')
        self.assertNotIn('password', response.data)
        self.assertNotIn('tipo', response.data)

    def test_atualizacao_de_perfil_respeita_campos_permitidos(self):
        self.client.force_authenticate(self.usuario)
        response = self.client.patch(
            self.meu_perfil_url,
            {
                'nome_completo': 'Paciente Um Atualizado',
                'nome_preferido': 'Paciente',
                'email': 'paciente.atualizado@example.com',
                'telefone': '82966665555',
                'data_nascimento': '1991-02-03',
                'endereco': {
                    'cep': '57000-111',
                    'logradouro': 'Avenida Principal',
                    'numero': '456',
                    'bairro': 'Farol',
                    'cidade': 'Maceio',
                    'estado': 'AL',
                },
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.nome_completo, 'Paciente Um Atualizado')
        self.assertEqual(self.usuario.email, 'paciente.atualizado@example.com')
        self.assertEqual(self.usuario.endereco.numero, '456')
        self.assertEqual(response.data['endereco']['bairro'], 'Farol')

    def test_alteracao_de_senha_usa_set_password(self):
        self.client.force_authenticate(self.usuario)
        response = self.client.post(
            self.alterar_senha_url,
            {'senha_atual': 'SenhaAtual123!', 'nova_senha': 'NovaSenhaForte123!'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('NovaSenhaForte123!'))
        self.assertNotEqual(self.usuario.password, 'NovaSenhaForte123!')

    def test_cors_nao_permite_todas_as_origens(self):
        self.assertFalse(settings.CORS_ALLOW_ALL_ORIGINS)
        self.assertIn('http://localhost:5173', settings.CORS_ALLOWED_ORIGINS)


class MultiClinicaViewSetTest(APITestCase):
    def setUp(self):
        self.clinica_a = Clinica.objects.create(nome='Clinica A')
        self.clinica_b = Clinica.objects.create(nome='Clinica B')
        criar_expediente(self.clinica_a)
        criar_expediente(self.clinica_b)
        self.staff = criar_usuario(
            username='staff',
            cpf='50000000001',
            email='staff@example.com',
            is_staff=True,
            tipo='ADMIN',
        )
        self.paciente_a = criar_usuario(
            username='paciente_a',
            cpf='50000000002',
            email='paciente.a@example.com',
            nome_completo='Paciente A',
            clinica=self.clinica_a,
        )
        self.paciente_b = criar_usuario(
            username='paciente_b',
            cpf='50000000003',
            email='paciente.b@example.com',
            nome_completo='Paciente B',
            clinica=self.clinica_b,
        )
        self.usuario_dentista_a = criar_usuario(
            username='dentista_a',
            cpf='50000000004',
            email='dentista.a@example.com',
            nome_completo='Dentista A',
            tipo='DENTISTA',
            clinica=self.clinica_a,
        )
        self.usuario_dentista_b = criar_usuario(
            username='dentista_b',
            cpf='50000000005',
            email='dentista.b@example.com',
            nome_completo='Dentista B',
            tipo='DENTISTA',
            clinica=self.clinica_b,
        )
        self.dentista_a = Dentista.objects.create(
            clinica=self.clinica_a,
            usuario=self.usuario_dentista_a,
            especialidade='Ortodontia',
            cro='CRO-A',
        )
        self.dentista_b = Dentista.objects.create(
            clinica=self.clinica_b,
            usuario=self.usuario_dentista_b,
            especialidade='Implantodontia',
            cro='CRO-B',
        )
        self.procedimento_a = Procedimento.objects.create(
            clinica=self.clinica_a,
            nome='Limpeza',
            duracao_minutos=30,
        )
        self.procedimento_b = Procedimento.objects.create(
            clinica=self.clinica_b,
            nome='Clareamento',
            duracao_minutos=45,
        )
        self.agendamento_b = Agendamento.objects.create(
            clinica=self.clinica_b,
            dentista=self.dentista_b,
            paciente=self.paciente_b,
            procedimento='Clareamento',
            procedimento_ref=self.procedimento_b,
            data_horario='2030-01-10T10:00:00Z',
        )

    def test_staff_consegue_criar_clinica(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            reverse('clinica-list'),
            {
                'nome': 'Clinica Nova',
                'cnpj': '12.345.678/0001-99',
                'telefone': '82911112222',
                'email': 'nova@example.com',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Clinica.objects.filter(nome='Clinica Nova').exists())

    def test_usuario_comum_lista_apenas_sua_clinica(self):
        self.client.force_authenticate(self.paciente_a)
        response = self.client.get(reverse('clinica-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.clinica_a.id)

    def test_endpoints_versionados_principais_respondem(self):
        self.client.force_authenticate(self.paciente_a)

        respostas = [
            self.client.get('/api/v1/clinicas/'),
            self.client.get('/api/v1/dentistas/'),
            self.client.get('/api/v1/procedimentos/'),
            self.client.get('/api/v1/agendamentos/'),
        ]

        for response in respostas:
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn('count', response.data)
            self.assertIn('next', response.data)
            self.assertIn('previous', response.data)
            self.assertIn('results', response.data)

    def test_usuario_de_clinica_a_nao_acessa_dentista_da_clinica_b(self):
        self.client.force_authenticate(self.paciente_a)
        response = self.client.get(reverse('dentista-detail', args=[self.dentista_b.pk]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_usuario_de_clinica_a_recebe_404_para_agendamento_da_clinica_b(self):
        self.client.force_authenticate(self.paciente_a)
        response = self.client.get(reverse('agendamento-detail', args=[self.agendamento_b.pk]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_usuario_de_clinica_a_nao_cria_agendamento_com_dentista_da_clinica_b(self):
        self.client.force_authenticate(self.paciente_a)
        response = self.client.post(
            reverse('agendamento-list'),
            {
                'dentista': self.dentista_b.pk,
                'procedimento': 'Consulta',
                'data_horario': '2030-01-11T10:00:00Z',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('dentista', response.data)

    def test_agendamento_com_dentista_invalido_retorna_400(self):
        self.client.force_authenticate(self.paciente_a)
        response = self.client.post(
            '/api/v1/agendamentos/',
            {
                'dentista': 999999,
                'procedimento': 'Consulta',
                'data_horario': '2030-01-11T10:00:00Z',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('dentista', response.data)

    def test_usuario_de_clinica_a_nao_cria_agendamento_com_procedimento_da_clinica_b(self):
        self.client.force_authenticate(self.paciente_a)
        response = self.client.post(
            reverse('agendamento-list'),
            {
                'dentista': self.dentista_a.pk,
                'procedimento_ref': self.procedimento_b.pk,
                'data_horario': '2030-01-12T10:00:00Z',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('procedimento_ref', response.data)

    def test_payload_legacy_medico_e_rejeitado_no_agendamento(self):
        self.client.force_authenticate(self.paciente_a)
        response = self.client.post(
            '/api/v1/agendamentos/',
            {
                'medico': self.dentista_a.pk,
                'procedimento': 'Consulta',
                'data_horario': '2030-01-11T10:00:00Z',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('medico', response.data)

    def test_agendamento_criado_por_usuario_comum_recebe_clinica_do_usuario(self):
        self.client.force_authenticate(self.paciente_a)
        response = self.client.post(
            reverse('agendamento-list'),
            {
                'dentista': self.dentista_a.pk,
                'procedimento_ref': self.procedimento_a.pk,
                'data_horario': '2030-01-13T10:00:00Z',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        agendamento = Agendamento.objects.get(pk=response.data['id'])
        self.assertEqual(agendamento.clinica_id, self.clinica_a.id)
        self.assertEqual(agendamento.paciente_id, self.paciente_a.id)
        self.assertEqual(agendamento.procedimento, 'Limpeza')

    def test_staff_criacao_de_dentista_com_cro_invalido_retorna_400(self):
        usuario_dentista = criar_usuario(
            username='dentista_cro_invalido',
            cpf='50000000006',
            email='dentista.invalido@example.com',
            nome_completo='Dentista Invalido',
            tipo='DENTISTA',
            clinica=self.clinica_a,
        )
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            '/api/v1/dentistas/',
            {
                'clinica': self.clinica_a.pk,
                'usuario': usuario_dentista.pk,
                'especialidade': 'Endodontia',
                'cro': 'CRM-123',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cro', response.data)


class ConfiguracoesComerciaisClinicaTest(APITestCase):
    def setUp(self):
        self.clinica_a = Clinica.objects.create(
            nome='Comercial Clinica A',
            slug='comercial-a',
            antecedencia_minima_cancelamento_horas=24,
            duracao_padrao_consulta_minutos=30,
        )
        self.clinica_b = Clinica.objects.create(nome='Comercial Clinica B', slug='comercial-b')
        self.staff = criar_usuario(
            'comercial_staff', '70000000001', 'comercial.staff@example.com', tipo='ADMIN', is_staff=True
        )
        self.paciente_a = criar_usuario(
            'comercial_paciente_a', '70000000002', 'comercial.paciente.a@example.com', clinica=self.clinica_a
        )
        self.paciente_b = criar_usuario(
            'comercial_paciente_b', '70000000003', 'comercial.paciente.b@example.com', clinica=self.clinica_b
        )
        self.usuario_dentista_a = criar_usuario(
            'comercial_dentista_a',
            '70000000004',
            'comercial.dentista.a@example.com',
            tipo='DENTISTA',
            clinica=self.clinica_a,
        )
        self.dentista_a = Dentista.objects.create(
            clinica=self.clinica_a, usuario=self.usuario_dentista_a, especialidade='Clinica geral', cro='44444-AL'
        )
        self.procedimento_a = Procedimento.objects.create(
            clinica=self.clinica_a, nome='Consulta comercial', duracao_minutos=30
        )

    def criar_agendamento_comercial(self, data_horario):
        return Agendamento.objects.create(
            clinica=self.clinica_a,
            dentista=self.dentista_a,
            paciente=self.paciente_a,
            procedimento=self.procedimento_a.nome,
            procedimento_ref=self.procedimento_a,
            data_horario=data_horario,
            data_hora_fim=data_horario + timedelta(minutes=30),
            duracao_minutos=30,
        )

    def test_staff_cria_e_atualiza_clinica_com_slug_e_timezone(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            reverse('clinica-list'),
            {
                'nome': 'Clinica Comercial Nova',
                'slug': 'clinica-comercial-nova',
                'timezone': 'America/Sao_Paulo',
                'antecedencia_minima_cancelamento_horas': 12,
                'duracao_padrao_consulta_minutos': 40,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['slug'], 'clinica-comercial-nova')

        patch_response = self.client.patch(
            reverse('clinica-detail', args=[response.data['id']]),
            {'timezone': 'America/Maceio', 'antecedencia_minima_cancelamento_horas': 6},
            format='json',
        )

        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['timezone'], 'America/Maceio')
        self.assertEqual(patch_response.data['antecedencia_minima_cancelamento_horas'], 6)

    def test_staff_cria_horario_de_funcionamento(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            reverse('horario-funcionamento-list'),
            {
                'clinica': self.clinica_a.pk,
                'dia_semana': 0,
                'horario_inicio': '08:00:00',
                'horario_fim': '18:00:00',
                'ativo': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['clinica'], self.clinica_a.pk)

    def test_agendamento_dentro_do_horario_de_funcionamento_e_aceito(self):
        criar_expediente(self.clinica_a, inicio=time(8, 0), fim=time(18, 0))
        self.client.force_authenticate(self.paciente_a)

        response = self.client.post(
            reverse('agendamento-list'),
            {
                'dentista': self.dentista_a.pk,
                'procedimento_ref': self.procedimento_a.pk,
                'data_horario': data_local_futura(self.clinica_a, hora=10).isoformat(),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cancelamento_dentro_da_antecedencia_permitida_funciona(self):
        criar_expediente(self.clinica_a)
        agendamento = self.criar_agendamento_comercial(data_local_futura(self.clinica_a, dias=5, hora=10))
        self.client.force_authenticate(self.paciente_a)

        response = self.client.post(reverse('agendamento-cancelar', args=[agendamento.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], Agendamento.STATUS_CANCELADA)

    def test_campos_invalidos_de_clinica_e_horario_retornam_400(self):
        self.client.force_authenticate(self.staff)

        self.assertEqual(
            self.client.post(
                reverse('clinica-list'), {'nome': 'Slug Duplicado', 'slug': 'comercial-a'}, format='json'
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                reverse('clinica-list'),
                {'nome': 'Timezone Ruim', 'slug': 'timezone-ruim', 'timezone': 'Brasil/Invalida'},
                format='json',
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                reverse('clinica-list'),
                {
                    'nome': 'Antecedencia Ruim',
                    'slug': 'antecedencia-ruim',
                    'antecedencia_minima_cancelamento_horas': -1,
                },
                format='json',
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                reverse('clinica-list'),
                {'nome': 'Duracao Ruim', 'slug': 'duracao-ruim', 'duracao_padrao_consulta_minutos': 0},
                format='json',
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                reverse('horario-funcionamento-list'),
                {
                    'clinica': self.clinica_a.pk,
                    'dia_semana': 0,
                    'horario_inicio': '18:00:00',
                    'horario_fim': '08:00:00',
                },
                format='json',
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                reverse('horario-funcionamento-list'),
                {
                    'clinica': self.clinica_a.pk,
                    'dia_semana': 9,
                    'horario_inicio': '08:00:00',
                    'horario_fim': '18:00:00',
                },
                format='json',
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_usuario_comum_nao_altera_configuracoes_nem_cria_horario(self):
        self.client.force_authenticate(self.paciente_a)

        response_clinica = self.client.patch(
            reverse('clinica-detail', args=[self.clinica_a.pk]),
            {'slug': 'slug-tentado'},
            format='json',
        )
        response_horario = self.client.post(
            reverse('horario-funcionamento-list'),
            {'clinica': self.clinica_a.pk, 'dia_semana': 0, 'horario_inicio': '08:00:00', 'horario_fim': '18:00:00'},
            format='json',
        )

        self.assertEqual(response_clinica.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response_horario.status_code, status.HTTP_403_FORBIDDEN)

    def test_usuario_comum_ve_apenas_horarios_da_propria_clinica(self):
        horario_a = HorarioFuncionamentoClinica.objects.create(
            clinica=self.clinica_a, dia_semana=0, horario_inicio=time(8, 0), horario_fim=time(18, 0)
        )
        horario_b = HorarioFuncionamentoClinica.objects.create(
            clinica=self.clinica_b, dia_semana=0, horario_inicio=time(8, 0), horario_fim=time(18, 0)
        )
        self.client.force_authenticate(self.paciente_a)

        lista = self.client.get(reverse('horario-funcionamento-list'))
        detalhe_b = self.client.get(reverse('horario-funcionamento-detail', args=[horario_b.pk]))

        self.assertEqual(lista.status_code, status.HTTP_200_OK)
        self.assertEqual(lista.data['count'], 1)
        self.assertEqual(lista.data['results'][0]['id'], horario_a.pk)
        self.assertEqual(detalhe_b.status_code, status.HTTP_404_NOT_FOUND)

    def test_agendamento_fora_do_expediente_retorna_400(self):
        criar_expediente(self.clinica_a, inicio=time(8, 0), fim=time(18, 0))
        self.client.force_authenticate(self.paciente_a)

        response = self.client.post(
            reverse('agendamento-list'),
            {
                'dentista': self.dentista_a.pk,
                'procedimento_ref': self.procedimento_a.pk,
                'data_horario': data_local_futura(self.clinica_a, hora=7).isoformat(),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('data_horario', response.data)

    def test_agendamento_em_dia_sem_expediente_retorna_400(self):
        criar_expediente(self.clinica_a, inicio=time(8, 0), fim=time(18, 0), dias=[0])
        self.client.force_authenticate(self.paciente_a)

        response = self.client.post(
            reverse('agendamento-list'),
            {
                'dentista': self.dentista_a.pk,
                'procedimento_ref': self.procedimento_a.pk,
                'data_horario': data_local_futura(self.clinica_a, hora=10, dia_semana=1).isoformat(),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('data_horario', response.data)

    def test_agendamento_terminando_apos_fechamento_retorna_400(self):
        HorarioFuncionamentoClinica.objects.create(
            clinica=self.clinica_a, dia_semana=0, horario_inicio=time(8, 0), horario_fim=time(18, 0)
        )
        procedimento_longo = Procedimento.objects.create(
            clinica=self.clinica_a, nome='Procedimento longo', duracao_minutos=60
        )
        self.client.force_authenticate(self.paciente_a)

        response = self.client.post(
            reverse('agendamento-list'),
            {
                'dentista': self.dentista_a.pk,
                'procedimento_ref': procedimento_longo.pk,
                'data_horario': data_local_futura(self.clinica_a, hora=17, minuto=30, dia_semana=0).isoformat(),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('data_horario', response.data)

    def test_paciente_nao_cancela_fora_da_antecedencia_minima(self):
        criar_expediente(self.clinica_a)
        agendamento = self.criar_agendamento_comercial(timezone.now() + timedelta(hours=2))
        self.client.force_authenticate(self.paciente_a)

        response = self.client.post(reverse('agendamento-cancelar', args=[agendamento.pk]))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('data_horario', response.data)

    def test_usuario_nao_usa_configuracao_de_outra_clinica_no_agendamento(self):
        criar_expediente(self.clinica_b, inicio=time(8, 0), fim=time(18, 0))
        self.client.force_authenticate(self.paciente_a)

        response = self.client.post(
            reverse('agendamento-list'),
            {
                'clinica': self.clinica_b.pk,
                'dentista': self.dentista_a.pk,
                'procedimento_ref': self.procedimento_a.pk,
                'data_horario': data_local_futura(self.clinica_a, hora=10).isoformat(),
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('data_horario', response.data)


class BloqueiosIndisponibilidadesCadastroSlugTest(APITestCase):
    def setUp(self):
        self.clinica_a = Clinica.objects.create(nome='Sprint Sete A', slug='sprint-sete-a')
        self.clinica_b = Clinica.objects.create(nome='Sprint Sete B', slug='sprint-sete-b')
        self.clinica_inativa = Clinica.objects.create(
            nome='Sprint Sete Inativa', slug='sprint-sete-inativa', ativa=False
        )
        criar_expediente(self.clinica_a, inicio=time(8, 0), fim=time(18, 0))
        criar_expediente(self.clinica_b, inicio=time(8, 0), fim=time(18, 0))
        self.staff = criar_usuario(
            'sprint7_staff', '80000000001', 'sprint7.staff@example.com', tipo='ADMIN', is_staff=True
        )
        self.paciente_a = criar_usuario(
            'sprint7_paciente_a', '80000000002', 'sprint7.paciente.a@example.com', clinica=self.clinica_a
        )
        self.paciente_b = criar_usuario(
            'sprint7_paciente_b', '80000000003', 'sprint7.paciente.b@example.com', clinica=self.clinica_b
        )
        self.usuario_dentista_a = criar_usuario(
            'sprint7_dentista_a',
            '80000000004',
            'sprint7.dentista.a@example.com',
            tipo='DENTISTA',
            clinica=self.clinica_a,
        )
        self.usuario_dentista_b = criar_usuario(
            'sprint7_dentista_b',
            '80000000005',
            'sprint7.dentista.b@example.com',
            tipo='DENTISTA',
            clinica=self.clinica_b,
        )
        self.dentista_a = Dentista.objects.create(
            clinica=self.clinica_a, usuario=self.usuario_dentista_a, especialidade='Ortodontia', cro='77777-AL'
        )
        self.dentista_b = Dentista.objects.create(
            clinica=self.clinica_b, usuario=self.usuario_dentista_b, especialidade='Endodontia', cro='88888-AL'
        )
        self.procedimento_a = Procedimento.objects.create(
            clinica=self.clinica_a, nome='Consulta sprint 7', duracao_minutos=30
        )

    def payload_cadastro_slug(self, **overrides):
        payload = {
            'username': 'paciente_slug',
            'password': 'SenhaForte123!',
            'nome_completo': 'Paciente Slug',
            'email': 'paciente.slug@example.com',
            'cpf': '987.654.321-00',
            'data_nascimento': '1992-06-10',
            'telefone': '82999991111',
        }
        payload.update(overrides)
        return payload

    def payload_agendamento(self, data_horario):
        return {
            'dentista': self.dentista_a.pk,
            'procedimento_ref': self.procedimento_a.pk,
            'data_horario': data_horario.isoformat(),
        }

    def test_staff_cria_bloqueio_e_indisponibilidade(self):
        self.client.force_authenticate(self.staff)
        inicio = data_local_futura(self.clinica_a, hora=10)
        fim = inicio + timedelta(hours=2)

        bloqueio = self.client.post(
            reverse('bloqueio-agenda-list'),
            {
                'clinica': self.clinica_a.pk,
                'inicio': inicio.isoformat(),
                'fim': fim.isoformat(),
                'motivo': 'Feriado local',
            },
            format='json',
        )
        indisponibilidade = self.client.post(
            reverse('indisponibilidade-dentista-list'),
            {
                'clinica': self.clinica_a.pk,
                'dentista': self.dentista_a.pk,
                'inicio': inicio.isoformat(),
                'fim': fim.isoformat(),
                'motivo': 'Ferias',
            },
            format='json',
        )

        self.assertEqual(bloqueio.status_code, status.HTTP_201_CREATED)
        self.assertEqual(indisponibilidade.status_code, status.HTTP_201_CREATED)

    def test_agendamento_fora_de_bloqueios_e_indisponibilidades_funciona(self):
        self.client.force_authenticate(self.paciente_a)
        response = self.client.post(
            reverse('agendamento-list'),
            self.payload_agendamento(data_local_futura(self.clinica_a, hora=10)),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_bloqueio_com_intervalo_invalido_retorna_400(self):
        self.client.force_authenticate(self.staff)
        inicio = data_local_futura(self.clinica_a, hora=10)
        response = self.client.post(
            reverse('bloqueio-agenda-list'),
            {'clinica': self.clinica_a.pk, 'inicio': inicio.isoformat(), 'fim': inicio.isoformat()},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('fim', response.data)

    def test_indisponibilidade_invalida_retorna_400(self):
        self.client.force_authenticate(self.staff)
        inicio = data_local_futura(self.clinica_a, hora=10)

        intervalo_invalido = self.client.post(
            reverse('indisponibilidade-dentista-list'),
            {
                'clinica': self.clinica_a.pk,
                'dentista': self.dentista_a.pk,
                'inicio': inicio.isoformat(),
                'fim': inicio.isoformat(),
            },
            format='json',
        )
        dentista_outra_clinica = self.client.post(
            reverse('indisponibilidade-dentista-list'),
            {
                'clinica': self.clinica_a.pk,
                'dentista': self.dentista_b.pk,
                'inicio': inicio.isoformat(),
                'fim': (inicio + timedelta(hours=1)).isoformat(),
            },
            format='json',
        )

        self.assertEqual(intervalo_invalido.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('fim', intervalo_invalido.data)
        self.assertEqual(dentista_outra_clinica.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('dentista', dentista_outra_clinica.data)

    def test_usuario_comum_nao_cria_bloqueio_ou_indisponibilidade(self):
        self.client.force_authenticate(self.paciente_a)
        inicio = data_local_futura(self.clinica_a, hora=10)
        fim = inicio + timedelta(hours=1)

        bloqueio = self.client.post(
            reverse('bloqueio-agenda-list'),
            {'clinica': self.clinica_b.pk, 'inicio': inicio.isoformat(), 'fim': fim.isoformat()},
            format='json',
        )
        indisponibilidade = self.client.post(
            reverse('indisponibilidade-dentista-list'),
            {
                'clinica': self.clinica_b.pk,
                'dentista': self.dentista_b.pk,
                'inicio': inicio.isoformat(),
                'fim': fim.isoformat(),
            },
            format='json',
        )

        self.assertEqual(bloqueio.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(indisponibilidade.status_code, status.HTTP_403_FORBIDDEN)

    def test_usuario_comum_ve_apenas_bloqueios_e_indisponibilidades_da_propria_clinica(self):
        inicio = data_local_futura(self.clinica_a, hora=10)
        bloqueio_a = BloqueioAgendaClinica.objects.create(
            clinica=self.clinica_a, inicio=inicio, fim=inicio + timedelta(hours=1)
        )
        bloqueio_b = BloqueioAgendaClinica.objects.create(
            clinica=self.clinica_b, inicio=inicio, fim=inicio + timedelta(hours=1)
        )
        indisponibilidade_a = IndisponibilidadeDentista.objects.create(
            clinica=self.clinica_a, dentista=self.dentista_a, inicio=inicio, fim=inicio + timedelta(hours=1)
        )
        indisponibilidade_b = IndisponibilidadeDentista.objects.create(
            clinica=self.clinica_b, dentista=self.dentista_b, inicio=inicio, fim=inicio + timedelta(hours=1)
        )

        self.client.force_authenticate(self.paciente_a)
        bloqueios = self.client.get(reverse('bloqueio-agenda-list'))
        bloqueio_b_detail = self.client.get(reverse('bloqueio-agenda-detail', args=[bloqueio_b.pk]))
        indisponibilidades = self.client.get(reverse('indisponibilidade-dentista-list'))
        indisponibilidade_b_detail = self.client.get(
            reverse('indisponibilidade-dentista-detail', args=[indisponibilidade_b.pk])
        )

        self.assertEqual(bloqueios.status_code, status.HTTP_200_OK)
        self.assertEqual(bloqueios.data['count'], 1)
        self.assertEqual(bloqueios.data['results'][0]['id'], bloqueio_a.pk)
        self.assertEqual(bloqueio_b_detail.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(indisponibilidades.status_code, status.HTTP_200_OK)
        self.assertEqual(indisponibilidades.data['count'], 1)
        self.assertEqual(indisponibilidades.data['results'][0]['id'], indisponibilidade_a.pk)
        self.assertEqual(indisponibilidade_b_detail.status_code, status.HTTP_404_NOT_FOUND)

    def test_agendamento_dentro_ou_sobreposto_a_bloqueio_ativo_retorna_409(self):
        inicio = data_local_futura(self.clinica_a, hora=10)
        BloqueioAgendaClinica.objects.create(
            clinica=self.clinica_a, inicio=inicio, fim=inicio + timedelta(hours=2), motivo='Manutencao'
        )
        self.client.force_authenticate(self.paciente_a)

        dentro = self.client.post(
            reverse('agendamento-list'), self.payload_agendamento(inicio + timedelta(minutes=30)), format='json'
        )
        sobreposto = self.client.post(
            reverse('agendamento-list'), self.payload_agendamento(inicio - timedelta(minutes=15)), format='json'
        )

        self.assertEqual(dentro.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(sobreposto.status_code, status.HTTP_409_CONFLICT)

    def test_bloqueio_inativo_nao_impede_agendamento(self):
        inicio = data_local_futura(self.clinica_a, hora=10)
        BloqueioAgendaClinica.objects.create(
            clinica=self.clinica_a, inicio=inicio, fim=inicio + timedelta(hours=1), ativo=False
        )
        self.client.force_authenticate(self.paciente_a)

        response = self.client.post(reverse('agendamento-list'), self.payload_agendamento(inicio), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_indisponibilidade_ativa_ou_parcial_retorna_409(self):
        inicio = data_local_futura(self.clinica_a, hora=10)
        IndisponibilidadeDentista.objects.create(
            clinica=self.clinica_a, dentista=self.dentista_a, inicio=inicio, fim=inicio + timedelta(hours=2)
        )
        self.client.force_authenticate(self.paciente_a)

        dentro = self.client.post(
            reverse('agendamento-list'), self.payload_agendamento(inicio + timedelta(minutes=30)), format='json'
        )
        parcial = self.client.post(
            reverse('agendamento-list'), self.payload_agendamento(inicio - timedelta(minutes=15)), format='json'
        )

        self.assertEqual(dentro.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(parcial.status_code, status.HTTP_409_CONFLICT)

    def test_indisponibilidade_inativa_nao_impede_agendamento(self):
        inicio = data_local_futura(self.clinica_a, hora=10)
        IndisponibilidadeDentista.objects.create(
            clinica=self.clinica_a,
            dentista=self.dentista_a,
            inicio=inicio,
            fim=inicio + timedelta(hours=1),
            ativo=False,
        )
        self.client.force_authenticate(self.paciente_a)

        response = self.client.post(reverse('agendamento-list'), self.payload_agendamento(inicio), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_bloqueio_de_outra_clinica_nao_interfere(self):
        inicio = data_local_futura(self.clinica_a, hora=10)
        BloqueioAgendaClinica.objects.create(clinica=self.clinica_b, inicio=inicio, fim=inicio + timedelta(hours=1))
        self.client.force_authenticate(self.paciente_a)

        response = self.client.post(reverse('agendamento-list'), self.payload_agendamento(inicio), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cadastro_publico_por_slug_cria_paciente_na_clinica_correta(self):
        response = self.client.post(
            '/api/v1/clinicas/sprint-sete-a/pacientes/',
            self.payload_cadastro_slug(tipo='ADMIN', clinica=self.clinica_b.pk),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        usuario = Usuario.objects.get(username='paciente_slug')
        self.assertEqual(usuario.tipo, 'PACIENTE')
        self.assertEqual(usuario.clinica_id, self.clinica_a.pk)
        self.assertNotIn('password', response.data)
        self.assertNotIn('tipo', response.data)

    def test_cadastro_publico_por_slug_valida_campos_e_contexto(self):
        criar_usuario('slug_existente', '98765432100', 'existente.slug@example.com', clinica=self.clinica_a)

        sem_cpf = self.client.post(
            '/api/v1/clinicas/sprint-sete-a/pacientes/', self.payload_cadastro_slug(cpf=''), format='json'
        )
        cpf_duplicado = self.client.post(
            '/api/v1/clinicas/sprint-sete-a/pacientes/',
            self.payload_cadastro_slug(username='cpf_dup', email='cpf.dup@example.com'),
            format='json',
        )
        email_duplicado = self.client.post(
            '/api/v1/clinicas/sprint-sete-a/pacientes/',
            self.payload_cadastro_slug(username='email_dup', cpf='11122233344', email='existente.slug@example.com'),
            format='json',
        )
        slug_inexistente = self.client.post(
            '/api/v1/clinicas/slug-inexistente/pacientes/',
            self.payload_cadastro_slug(
                username='slug_inexistente', cpf='11122233345', email='slug.inexistente@example.com'
            ),
            format='json',
        )
        clinica_inativa = self.client.post(
            '/api/v1/clinicas/sprint-sete-inativa/pacientes/',
            self.payload_cadastro_slug(
                username='clinica_inativa', cpf='11122233346', email='clinica.inativa@example.com'
            ),
            format='json',
        )

        self.assertEqual(sem_cpf.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cpf', sem_cpf.data)
        self.assertEqual(cpf_duplicado.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cpf', cpf_duplicado.data)
        self.assertEqual(email_duplicado.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', email_duplicado.data)
        self.assertEqual(slug_inexistente.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(clinica_inativa.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('clinica', clinica_inativa.data)


class ConviteCadastroPacienteViewSetTest(APITestCase):
    def setUp(self):
        self.clinica_a = Clinica.objects.create(nome='Convites Clinica A')
        self.clinica_b = Clinica.objects.create(nome='Convites Clinica B')
        self.clinica_inativa = Clinica.objects.create(nome='Convites Clinica Inativa', ativa=False)
        self.staff = criar_usuario(
            'convite_staff', '70000000001', 'convite.staff@example.com', tipo='ADMIN', is_staff=True
        )
        self.usuario_a = criar_usuario(
            'convite_usuario_a', '70000000002', 'convite.usuario.a@example.com', clinica=self.clinica_a
        )
        self.usuario_b = criar_usuario(
            'convite_usuario_b', '70000000003', 'convite.usuario.b@example.com', clinica=self.clinica_b
        )
        self.lista_url = reverse('convite-paciente-list')

    def payload_convite(self, **overrides):
        payload = {
            'clinica': self.clinica_a.pk,
            'nome_destino': 'Paciente Convidado',
            'telefone_destino': '82999990000',
            'email_destino': 'convidado@example.com',
            'expira_em': (timezone.now() + timedelta(days=2)).isoformat(),
        }
        payload.update(overrides)
        return payload

    def payload_cadastro(self, **overrides):
        payload = {
            'username': 'paciente_por_convite',
            'password': 'SenhaForte123!',
            'nome_completo': 'Paciente por Convite',
            'email': 'paciente.convite@example.com',
            'cpf': '70000000004',
            'data_nascimento': '1994-05-10',
            'telefone': '82988887777',
        }
        payload.update(overrides)
        return payload

    def criar_convite(self, **overrides):
        dados = self.payload_convite(**overrides)
        clinica = dados.pop('clinica')
        if not isinstance(clinica, Clinica):
            clinica = Clinica.objects.get(pk=clinica)
        return ConviteCadastroPaciente.objects.create(**dados, clinica=clinica, criado_por=self.staff)

    def url_cadastro(self, convite):
        return reverse('convite-paciente-cadastrar', kwargs={'token': convite.token})

    def test_staff_cria_convite_ativo_e_recebe_token_e_link(self):
        self.client.force_authenticate(self.staff)

        response = self.client.post(self.lista_url, self.payload_convite(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        convite = ConviteCadastroPaciente.objects.get(pk=response.data['id'])
        self.assertEqual(convite.clinica_id, self.clinica_a.id)
        self.assertEqual(convite.criado_por_id, self.staff.id)
        self.assertTrue(response.data['token'])
        self.assertIn(response.data['token'], response.data['endpoint_cadastro'])
        self.assertIn('link_cadastro', response.data)

        listagem = self.client.get(self.lista_url)
        self.assertEqual(listagem.status_code, status.HTTP_200_OK)
        self.assertNotIn('token', listagem.data['results'][0])

    def test_cadastro_por_token_valido_cria_paciente_na_clinica_e_consumo_unico(self):
        convite = self.criar_convite()

        response = self.client.post(
            self.url_cadastro(convite),
            self.payload_cadastro(tipo='ADMIN', clinica=self.clinica_b.pk),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        usuario = Usuario.objects.get(username='paciente_por_convite')
        convite.refresh_from_db()
        self.assertEqual(usuario.tipo, 'PACIENTE')
        self.assertEqual(usuario.clinica_id, self.clinica_a.id)
        self.assertIsNotNone(convite.usado_em)
        self.assertNotIn('password', response.data)
        self.assertNotIn('tipo', response.data)

        reutilizacao = self.client.post(self.url_cadastro(convite), self.payload_cadastro(), format='json')
        self.assertEqual(reutilizacao.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('convite', reutilizacao.data)

    def test_campos_invalidos_nao_consumem_convite(self):
        convite = self.criar_convite()
        criar_usuario('convite_existente', '70000000005', 'existente.convite@example.com')

        sem_cpf = self.client.post(self.url_cadastro(convite), self.payload_cadastro(cpf=''), format='json')
        cpf_duplicado = self.client.post(
            self.url_cadastro(convite),
            self.payload_cadastro(username='cpf_duplicado', cpf='70000000005'),
            format='json',
        )
        email_duplicado = self.client.post(
            self.url_cadastro(convite),
            self.payload_cadastro(username='email_duplicado', cpf='70000000006', email='existente.convite@example.com'),
            format='json',
        )
        senha_invalida = self.client.post(
            self.url_cadastro(convite),
            self.payload_cadastro(
                username='senha_invalida', cpf='70000000007', email='senha.invalida@example.com', password='12345678'
            ),
            format='json',
        )

        for response in (sem_cpf, cpf_duplicado, email_duplicado, senha_invalida):
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        convite.refresh_from_db()
        self.assertIsNone(convite.usado_em)

    def test_convite_inexistente_expirado_inativo_ou_clinica_inativa_retorna_erro_controlado(self):
        expirado = self.criar_convite(expira_em=timezone.now() - timedelta(minutes=1))
        inativo = self.criar_convite(email_destino='inativo@example.com', ativo=False)
        clinica_inativa = self.criar_convite(clinica=self.clinica_inativa, email_destino='clinica.inativa@example.com')

        inexistente = self.client.post(
            '/api/v1/convites-pacientes/token-inexistente/cadastrar/', self.payload_cadastro(), format='json'
        )
        expirado_response = self.client.post(self.url_cadastro(expirado), self.payload_cadastro(), format='json')
        inativo_response = self.client.post(self.url_cadastro(inativo), self.payload_cadastro(), format='json')
        clinica_inativa_response = self.client.post(
            self.url_cadastro(clinica_inativa), self.payload_cadastro(), format='json'
        )

        self.assertEqual(inexistente.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(expirado_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(inativo_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(clinica_inativa_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_criacao_de_convite_valida_clinica_e_expiracao(self):
        self.client.force_authenticate(self.staff)

        inexistente = self.client.post(self.lista_url, self.payload_convite(clinica=999999), format='json')
        inativa = self.client.post(self.lista_url, self.payload_convite(clinica=self.clinica_inativa.pk), format='json')
        expirada = self.client.post(
            self.lista_url,
            self.payload_convite(expira_em=(timezone.now() - timedelta(minutes=1)).isoformat()),
            format='json',
        )

        self.assertEqual(inexistente.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(inativa.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(expirada.status_code, status.HTTP_400_BAD_REQUEST)

    def test_usuario_comum_nao_cria_nem_altera_e_nao_acessa_convite_de_outra_clinica(self):
        convite_a = self.criar_convite()
        convite_b = self.criar_convite(clinica=self.clinica_b, email_destino='clinica.b@example.com')
        self.client.force_authenticate(self.usuario_a)

        criacao = self.client.post(self.lista_url, self.payload_convite(clinica=self.clinica_b.pk), format='json')
        alteracao = self.client.patch(
            reverse('convite-paciente-detail', kwargs={'token': convite_a.token}), {'ativo': False}, format='json'
        )
        listagem = self.client.get(self.lista_url)
        detalhe_outra_clinica = self.client.get(reverse('convite-paciente-detail', kwargs={'token': convite_b.token}))

        self.assertEqual(criacao.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(alteracao.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(listagem.status_code, status.HTTP_200_OK)
        self.assertEqual(listagem.data['count'], 1)
        self.assertEqual(listagem.data['results'][0]['id'], convite_a.id)
        self.assertEqual(detalhe_outra_clinica.status_code, status.HTTP_404_NOT_FOUND)


class DocumentacaoApiTest(APITestCase):
    def test_schema_openapi_e_gerado_sem_erro(self):
        response = self.client.get('/api/schema/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_docs_swagger_e_redoc_respondem(self):
        swagger_response = self.client.get('/api/docs/')
        redoc_response = self.client.get('/api/redoc/')

        self.assertEqual(swagger_response.status_code, status.HTTP_200_OK)
        self.assertEqual(redoc_response.status_code, status.HTTP_200_OK)

    def test_rota_inexistente_retorna_404(self):
        response = self.client.get('/api/v1/rota-inexistente/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AgendaFluxoViewSetTest(APITestCase):
    def setUp(self):
        self.clinica_a = Clinica.objects.create(nome='Agenda Clinica A')
        self.clinica_b = Clinica.objects.create(nome='Agenda Clinica B')
        criar_expediente(self.clinica_a)
        criar_expediente(self.clinica_b)
        self.staff = criar_usuario(
            'agenda_staff', '60000000001', 'agenda.staff@example.com', tipo='ADMIN', is_staff=True
        )
        self.paciente_a = criar_usuario(
            'agenda_paciente_a', '60000000002', 'agenda.paciente.a@example.com', clinica=self.clinica_a
        )
        self.paciente_b = criar_usuario(
            'agenda_paciente_b', '60000000003', 'agenda.paciente.b@example.com', clinica=self.clinica_b
        )
        self.usuario_dentista_a = criar_usuario(
            'agenda_dentista_a', '60000000004', 'agenda.dentista.a@example.com', tipo='DENTISTA', clinica=self.clinica_a
        )
        self.usuario_dentista_b = criar_usuario(
            'agenda_dentista_b', '60000000005', 'agenda.dentista.b@example.com', tipo='DENTISTA', clinica=self.clinica_b
        )
        self.dentista_a = Dentista.objects.create(
            clinica=self.clinica_a, usuario=self.usuario_dentista_a, especialidade='Ortodontia', cro='11111-AL'
        )
        self.dentista_b = Dentista.objects.create(
            clinica=self.clinica_b, usuario=self.usuario_dentista_b, especialidade='Endodontia', cro='22222-AL'
        )
        self.dentista_inativo = Dentista.objects.create(
            clinica=self.clinica_a,
            usuario=criar_usuario(
                'agenda_dentista_inativo',
                '60000000006',
                'agenda.inativo@example.com',
                tipo='DENTISTA',
                clinica=self.clinica_a,
            ),
            especialidade='Periodontia',
            cro='33333-AL',
            ativo=False,
        )
        self.procedimento_a = Procedimento.objects.create(
            clinica=self.clinica_a, nome='Limpeza agenda', duracao_minutos=30
        )
        self.procedimento_b = Procedimento.objects.create(
            clinica=self.clinica_b, nome='Clareamento agenda', duracao_minutos=45
        )
        self.procedimento_inativo = Procedimento.objects.create(
            clinica=self.clinica_a, nome='Inativo agenda', duracao_minutos=30, ativo=False
        )

    def futuro(self, dias=20, horas=0, minutos=0):
        return data_local_futura(self.clinica_a, dias=dias, hora=10, minuto=0) + timedelta(hours=horas, minutes=minutos)

    def payload_agendamento(self, **overrides):
        payload = {
            'dentista': self.dentista_a.pk,
            'procedimento_ref': self.procedimento_a.pk,
            'data_horario': self.futuro().isoformat(),
        }
        payload.update(overrides)
        return payload

    def criar_agendamento(self, **overrides):
        inicio = overrides.pop('data_horario', self.futuro(dias=30))
        duracao = overrides.pop('duracao_minutos', 30)
        return Agendamento.objects.create(
            clinica=overrides.pop('clinica', self.clinica_a),
            dentista=overrides.pop('dentista', self.dentista_a),
            paciente=overrides.pop('paciente', self.paciente_a),
            procedimento=overrides.pop('procedimento', self.procedimento_a.nome),
            procedimento_ref=overrides.pop('procedimento_ref', self.procedimento_a),
            data_horario=inicio,
            data_hora_fim=inicio + timedelta(minutes=duracao),
            duracao_minutos=duracao,
            status=overrides.pop('status', Agendamento.STATUS_AGENDADA),
        )

    def test_paciente_cria_agendamento_valido_para_si_mesmo(self):
        self.client.force_authenticate(self.paciente_a)
        response = self.client.post('/api/v1/agendamentos/', self.payload_agendamento(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        agendamento = Agendamento.objects.get(pk=response.data['id'])
        self.assertEqual(agendamento.paciente_id, self.paciente_a.id)
        self.assertEqual(agendamento.clinica_id, self.clinica_a.id)
        self.assertEqual(agendamento.status, Agendamento.STATUS_AGENDADA)
        self.assertIsNotNone(agendamento.data_hora_fim)

    def test_staff_cria_agendamento_valido(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(
            '/api/v1/agendamentos/',
            self.payload_agendamento(
                clinica=self.clinica_a.pk, paciente=self.paciente_a.pk, data_horario=self.futuro(dias=21).isoformat()
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['clinica'], self.clinica_a.id)

    def test_acoes_validas_alteram_status(self):
        agendamento = self.criar_agendamento()
        self.client.force_authenticate(self.paciente_a)
        self.assertEqual(
            self.client.post(reverse('agendamento-cancelar', args=[agendamento.pk])).data['status'],
            Agendamento.STATUS_CANCELADA,
        )

        agendamento = self.criar_agendamento(data_horario=self.futuro(dias=31))
        self.client.force_authenticate(self.usuario_dentista_a)
        self.assertEqual(
            self.client.post(reverse('agendamento-confirmar', args=[agendamento.pk])).data['status'],
            Agendamento.STATUS_CONFIRMADA,
        )
        self.assertEqual(
            self.client.post(reverse('agendamento-concluir', args=[agendamento.pk])).data['status'],
            Agendamento.STATUS_CONCLUIDA,
        )

        agendamento = self.criar_agendamento(data_horario=self.futuro(dias=32))
        self.assertEqual(
            self.client.post(reverse('agendamento-marcar-falta', args=[agendamento.pk])).data['status'],
            Agendamento.STATUS_NAO_COMPARECEU,
        )

    def test_reagendamento_valido_altera_data_hora(self):
        agendamento = self.criar_agendamento()
        nova_data = self.futuro(dias=40)
        self.client.force_authenticate(self.paciente_a)
        response = self.client.post(
            reverse('agendamento-reagendar', args=[agendamento.pk]),
            {'data_horario': nova_data.isoformat()},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        agendamento.refresh_from_db()
        self.assertEqual(agendamento.data_horario.replace(microsecond=0), nova_data.replace(microsecond=0))

    def test_campos_invalidos_retornam_400(self):
        self.client.force_authenticate(self.paciente_a)
        self.assertEqual(
            self.client.post(
                '/api/v1/agendamentos/', self.payload_agendamento(dentista=None), format='json'
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                '/api/v1/agendamentos/',
                {'dentista': self.dentista_a.pk, 'procedimento_ref': self.procedimento_a.pk},
                format='json',
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                '/api/v1/agendamentos/',
                self.payload_agendamento(data_horario=(timezone.now() - timedelta(days=1)).isoformat()),
                format='json',
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                '/api/v1/agendamentos/', self.payload_agendamento(dentista=999999), format='json'
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                '/api/v1/agendamentos/', self.payload_agendamento(procedimento_ref=999999), format='json'
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                '/api/v1/agendamentos/', self.payload_agendamento(status='INVALIDO'), format='json'
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                reverse('agendamento-reagendar', args=[self.criar_agendamento().pk]), {}, format='json'
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_dentista_ou_procedimento_inativo_retornam_400(self):
        self.client.force_authenticate(self.paciente_a)
        self.assertEqual(
            self.client.post(
                '/api/v1/agendamentos/', self.payload_agendamento(dentista=self.dentista_inativo.pk), format='json'
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(
                '/api/v1/agendamentos/',
                self.payload_agendamento(procedimento_ref=self.procedimento_inativo.pk),
                format='json',
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_paciente_nao_executa_acoes_profissionais(self):
        agendamento = self.criar_agendamento()
        self.client.force_authenticate(self.paciente_a)

        self.assertEqual(
            self.client.post(reverse('agendamento-confirmar', args=[agendamento.pk])).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(reverse('agendamento-concluir', args=[agendamento.pk])).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(reverse('agendamento-marcar-falta', args=[agendamento.pk])).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_patch_generico_nao_troca_campos_sensiveis(self):
        agendamento = self.criar_agendamento()
        self.client.force_authenticate(self.paciente_a)
        response = self.client.patch(
            reverse('agendamento-detail', args=[agendamento.pk]),
            {
                'status': Agendamento.STATUS_CONCLUIDA,
                'dentista': self.dentista_b.pk,
                'paciente': self.paciente_b.pk,
                'clinica': self.clinica_b.pk,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        agendamento.refresh_from_db()
        self.assertEqual(agendamento.status, Agendamento.STATUS_AGENDADA)
        self.assertEqual(agendamento.dentista_id, self.dentista_a.id)

    def test_acesso_indevido_retorna_404(self):
        agendamento_outro_paciente = self.criar_agendamento(
            paciente=criar_usuario('agenda_outro', '60000000007', 'agenda.outro@example.com', clinica=self.clinica_a)
        )
        agendamento_b = self.criar_agendamento(
            clinica=self.clinica_b,
            dentista=self.dentista_b,
            paciente=self.paciente_b,
            procedimento_ref=self.procedimento_b,
            procedimento=self.procedimento_b.nome,
            data_horario=self.futuro(dias=33),
        )

        self.client.force_authenticate(self.paciente_a)
        self.assertEqual(
            self.client.get(reverse('agendamento-detail', args=[agendamento_outro_paciente.pk])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(reverse('agendamento-cancelar', args=[agendamento_outro_paciente.pk])).status_code,
            status.HTTP_404_NOT_FOUND,
        )

        self.client.force_authenticate(self.usuario_dentista_a)
        self.assertEqual(
            self.client.get(reverse('agendamento-detail', args=[agendamento_b.pk])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(
                reverse('agendamento-reagendar', args=[agendamento_b.pk]),
                {'data_horario': self.futuro(dias=34).isoformat()},
                format='json',
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_payload_nao_burla_clinica_ou_paciente(self):
        self.client.force_authenticate(self.paciente_a)
        response = self.client.post(
            '/api/v1/agendamentos/',
            self.payload_agendamento(
                clinica=self.clinica_b.pk, paciente=self.paciente_b.pk, data_horario=self.futuro(dias=35).isoformat()
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        agendamento = Agendamento.objects.get(pk=response.data['id'])
        self.assertEqual(agendamento.clinica_id, self.clinica_a.id)
        self.assertEqual(agendamento.paciente_id, self.paciente_a.id)

    def test_conflito_exato_e_sobreposicao_retornam_409(self):
        inicio = self.futuro(dias=50)
        self.criar_agendamento(data_horario=inicio, duracao_minutos=60)
        self.client.force_authenticate(self.paciente_a)

        conflito_exato = self.client.post(
            '/api/v1/agendamentos/', self.payload_agendamento(data_horario=inicio.isoformat()), format='json'
        )
        sobreposicao = self.client.post(
            '/api/v1/agendamentos/',
            self.payload_agendamento(data_horario=(inicio + timedelta(minutes=30)).isoformat()),
            format='json',
        )

        self.assertEqual(conflito_exato.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(sobreposicao.status_code, status.HTTP_409_CONFLICT)

    def test_cancelado_nao_bloqueia_horario(self):
        inicio = self.futuro(dias=60)
        self.criar_agendamento(data_horario=inicio, status=Agendamento.STATUS_CANCELADA)
        self.client.force_authenticate(self.paciente_a)

        response = self.client.post(
            '/api/v1/agendamentos/', self.payload_agendamento(data_horario=inicio.isoformat()), format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_transicoes_invalidas_retornam_400(self):
        concluido = self.criar_agendamento(status=Agendamento.STATUS_CONCLUIDA)
        cancelado = self.criar_agendamento(data_horario=self.futuro(dias=61), status=Agendamento.STATUS_CANCELADA)
        self.client.force_authenticate(self.usuario_dentista_a)

        self.assertEqual(
            self.client.post(reverse('agendamento-cancelar', args=[concluido.pk])).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(reverse('agendamento-concluir', args=[cancelado.pk])).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            self.client.post(reverse('agendamento-confirmar', args=[cancelado.pk])).status_code,
            status.HTTP_400_BAD_REQUEST,
        )
