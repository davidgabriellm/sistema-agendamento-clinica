import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from api.models import (
    AcessoArquivoClinico,
    Agendamento,
    ArquivoClinico,
    Clinica,
    Dentista,
    ProntuarioPaciente,
    SolicitacaoAnonimizacao,
    Usuario,
)


def usuario(username, cpf, email, clinica, tipo='PACIENTE', staff=False):
    return Usuario.objects.create_user(
        username=username,
        password='SenhaAtual123!',
        nome_completo=username,
        email=email,
        cpf=cpf,
        telefone='82999990000',
        data_nascimento='1990-01-01',
        clinica=clinica,
        tipo=tipo,
        is_staff=staff,
    )


class ArquivosConsentimentosTest(APITestCase):
    """Sprint 12: uploads, consentimento, privacidade e isolamento."""

    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_dir.cleanup)

        self.clinica = Clinica.objects.create(nome='Clinica LGPD')
        self.outra = Clinica.objects.create(nome='Outra Clinica LGPD')
        self.staff = usuario('staff_lgpd', '95000000001', 'staff.lgpd@example.com', self.clinica, 'ADMIN', True)
        self.paciente = usuario('paciente_lgpd', '95000000002', 'paciente.lgpd@example.com', self.clinica)
        self.paciente_mesma_clinica = usuario(
            'paciente_lgpd_2', '95000000003', 'paciente2.lgpd@example.com', self.clinica
        )
        self.outro = usuario('outro_lgpd', '95000000004', 'outro.lgpd@example.com', self.outra)
        self.dentista_usuario = usuario(
            'dentista_lgpd', '95000000005', 'dentista.lgpd@example.com', self.clinica, 'DENTISTA'
        )
        self.dentista_outro = usuario(
            'dentista_lgpd_b', '95000000006', 'dentista.b.lgpd@example.com', self.outra, 'DENTISTA'
        )
        self.dentista = Dentista.objects.create(
            clinica=self.clinica, usuario=self.dentista_usuario, especialidade='Clinico', cro='95001-AL'
        )
        Dentista.objects.create(
            clinica=self.outra, usuario=self.dentista_outro, especialidade='Clinico', cro='95002-AL'
        )
        self.prontuario = ProntuarioPaciente.objects.create(
            clinica=self.clinica, paciente=self.paciente, criado_por=self.staff
        )
        self.prontuario_outro = ProntuarioPaciente.objects.create(
            clinica=self.outra, paciente=self.outro, criado_por=self.staff
        )
        inicio = timezone.now() + timedelta(days=1)
        self.agendamento = Agendamento.objects.create(
            clinica=self.clinica,
            dentista=self.dentista,
            paciente=self.paciente,
            procedimento='Consulta',
            data_horario=inicio,
            data_hora_fim=inicio + timedelta(minutes=30),
            duracao_minutos=30,
        )

    def arquivo_pdf(self, nome='exame.pdf', conteudo=b'%PDF-1.4 teste', mime='application/pdf'):
        return SimpleUploadedFile(nome, conteudo, content_type=mime)

    def enviar_arquivo(self, **dados):
        payload = {
            'paciente': self.paciente.id,
            'categoria': 'EXAME',
            'liberado_paciente': True,
            'arquivo': self.arquivo_pdf(),
        }
        payload.update(dados)
        self.client.force_authenticate(self.staff)
        return self.client.post('/api/v1/arquivos-clinicos/', payload, format='multipart')

    def criar_termo(self, **dados):
        payload = {'titulo': 'Uso de dados', 'codigo': 'uso-dados', 'versao': 1, 'conteudo': 'Texto do termo'}
        payload.update(dados)
        self.client.force_authenticate(self.staff)
        return self.client.post('/api/v1/termos-consentimento/', payload, format='json')

    def test_upload_valido_download_auditoria_e_headers(self):
        envio = self.enviar_arquivo(prontuario=self.prontuario.id, agendamento=self.agendamento.id)
        self.assertEqual(envio.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(envio.data['hash_sha256']), 64)
        self.assertEqual(envio.data['clinica'], self.clinica.id)
        self.client.force_authenticate(self.paciente)
        resposta = self.client.get(f'/api/v1/arquivos-clinicos/{envio.data["id"]}/download/', HTTP_USER_AGENT='teste')
        self.assertEqual(resposta.status_code, status.HTTP_200_OK)
        self.assertEqual(resposta['X-Content-Type-Options'], 'nosniff')
        self.assertTrue(
            AcessoArquivoClinico.objects.filter(
                arquivo_id=envio.data['id'], usuario=self.paciente, acao='DOWNLOAD'
            ).exists()
        )
        resposta.close()

    def test_upload_rejeita_vazio_limite_mime_extensao_nome_duplo_e_executavel(self):
        casos = [
            self.arquivo_pdf('vazio.pdf', b''),
            self.arquivo_pdf('proibido.txt', b'%PDF-1.4', 'text/plain'),
            self.arquivo_pdf('mime.pdf', b'%PDF-1.4', 'text/plain'),
            self.arquivo_pdf('duplo.pdf.exe', b'MZ', 'application/pdf'),
            self.arquivo_pdf('disfarcado.pdf', b'MZ', 'application/pdf'),
        ]
        with override_settings(ARQUIVO_CLINICO_MAX_TAMANHO_BYTES=5):
            grande = self.arquivo_pdf('grande.pdf', b'%PDF-1.4 maior')
            self.assertEqual(self.enviar_arquivo(arquivo=grande).status_code, status.HTTP_400_BAD_REQUEST)
        for arquivo in casos:
            self.assertEqual(self.enviar_arquivo(arquivo=arquivo).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ArquivoClinico.objects.count(), 0)

    def test_upload_invalido_nao_deixa_arquivo_orfao(self):
        resposta = self.enviar_arquivo(arquivo=self.arquivo_pdf('falha.pdf', b'MZ'))
        self.assertEqual(resposta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(list(Path(settings.MEDIA_ROOT).rglob('*')))

    def test_rejeita_prontuario_e_agendamento_incompativeis(self):
        self.assertEqual(
            self.enviar_arquivo(prontuario=self.prontuario_outro.id).status_code, status.HTTP_400_BAD_REQUEST
        )
        inicio = timezone.now() + timedelta(days=2)
        agendamento_outro = Agendamento.objects.create(
            clinica=self.outra,
            dentista=Dentista.objects.get(usuario=self.dentista_outro),
            paciente=self.outro,
            procedimento='Consulta',
            data_horario=inicio,
            data_hora_fim=inicio + timedelta(minutes=30),
            duracao_minutos=30,
        )
        self.assertEqual(self.enviar_arquivo(agendamento=agendamento_outro.id).status_code, status.HTTP_400_BAD_REQUEST)

    def test_isolamento_paciente_e_dentista_outra_clinica(self):
        arquivo = self.enviar_arquivo().data
        self.client.force_authenticate(self.paciente_mesma_clinica)
        self.assertEqual(
            self.client.get(f'/api/v1/arquivos-clinicos/{arquivo["id"]}/download/').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.client.force_authenticate(self.dentista_outro)
        self.assertEqual(
            self.client.get(f'/api/v1/arquivos-clinicos/{arquivo["id"]}/').status_code, status.HTTP_404_NOT_FOUND
        )

    def test_vinculos_criticos_sao_imutaveis_e_desativado_nao_baixa(self):
        arquivo = self.enviar_arquivo().data
        self.client.force_authenticate(self.staff)
        for campo, valor in {
            'clinica': self.outra.id,
            'paciente': self.outro.id,
            'hash_sha256': '0' * 64,
            'enviado_por': self.outro.id,
            'prontuario': self.prontuario_outro.id,
        }.items():
            self.assertEqual(
                self.client.patch(
                    f'/api/v1/arquivos-clinicos/{arquivo["id"]}/', {campo: valor}, format='json'
                ).status_code,
                status.HTTP_400_BAD_REQUEST,
            )
        self.assertEqual(
            self.client.post(f'/api/v1/arquivos-clinicos/{arquivo["id"]}/desativar/').status_code, status.HTTP_200_OK
        )
        self.client.force_authenticate(self.paciente)
        self.assertEqual(
            self.client.get(f'/api/v1/arquivos-clinicos/{arquivo["id"]}/download/').status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_termo_inativo_duplicado_e_aceite_de_outro_paciente(self):
        inativo = self.criar_termo(codigo='inativo', ativo=False)
        self.client.force_authenticate(self.paciente)
        self.assertEqual(
            self.client.post(f'/api/v1/termos-consentimento/{inativo.data["id"]}/aceitar/').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        termo = self.criar_termo(codigo='duplicado')
        self.assertEqual(self.criar_termo(codigo='duplicado').status_code, status.HTTP_400_BAD_REQUEST)
        self.client.force_authenticate(self.paciente)
        aceite = self.client.post(
            f'/api/v1/termos-consentimento/{termo.data["id"]}/aceitar/',
            {'paciente': self.paciente_mesma_clinica.id},
            format='json',
        )
        self.assertEqual(aceite.status_code, status.HTTP_201_CREATED)
        self.assertEqual(aceite.data['paciente'], self.paciente.id)

    def test_revogacao_repetida_exportacao_sem_segredos_e_isolamento(self):
        termo = self.criar_termo(codigo='exportacao')
        self.client.force_authenticate(self.paciente)
        aceite = self.client.post(f'/api/v1/termos-consentimento/{termo.data["id"]}/aceitar/')
        self.assertEqual(
            self.client.post(f'/api/v1/consentimentos/{aceite.data["id"]}/revogar/').status_code, status.HTTP_200_OK
        )
        self.assertEqual(
            self.client.post(f'/api/v1/consentimentos/{aceite.data["id"]}/revogar/').status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        exportacao = self.client.post(f'/api/v1/usuarios/{self.paciente.id}/exportar-dados/')
        self.assertEqual(exportacao.status_code, status.HTTP_200_OK)
        texto = str(exportacao.data).lower()
        self.assertNotIn('password', texto)
        self.assertNotIn('secret_key', texto)
        self.assertNotIn('token', texto)
        self.assertEqual(
            self.client.post(f'/api/v1/usuarios/{self.outro.id}/exportar-dados/').status_code, status.HTTP_404_NOT_FOUND
        )

    def test_anonimizacao_de_outro_usuario_e_bloqueada(self):
        self.client.force_authenticate(self.paciente)
        self.assertEqual(
            self.client.post(
                f'/api/v1/usuarios/{self.outro.id}/solicitar-anonimizacao/', {'motivo': 'teste'}, format='json'
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        resposta = self.client.post(
            f'/api/v1/usuarios/{self.paciente.id}/solicitar-anonimizacao/', {'motivo': 'teste'}, format='json'
        )
        self.assertEqual(resposta.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SolicitacaoAnonimizacao.objects.filter(paciente=self.paciente).count(), 1)
