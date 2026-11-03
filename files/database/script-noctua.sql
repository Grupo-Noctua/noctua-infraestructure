SELECT 1;
SHOW DATABASES;
SELECT CURRENT_USER();

CREATE DATABASE NOCTUA;
USE NOCTUA;

CREATE TABLE Processamento (
    id_processamento INT AUTO_INCREMENT PRIMARY KEY,
    quantidade_consultores INT NOT NULL,
    senioridades_selecionadas JSON NULL,
    nome_arquivo_pdf VARCHAR(255) NULL,
    dt_processamento DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Processamento_Log_JSON (
    id_log INT AUTO_INCREMENT PRIMARY KEY,
    fk_processamento INT NOT NULL,
    etapa VARCHAR(50) NOT NULL,
    conteudo JSON NOT NULL,
    dt_inclusao DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (fk_processamento) REFERENCES Processamento(id_processamento)
);

CREATE TABLE Documento_Projeto (
    id_documento INT AUTO_INCREMENT PRIMARY KEY,
    fk_processamento INT NOT NULL,
    nome_projeto VARCHAR(255) NULL,
    cliente VARCHAR(255) NULL,
    gestor_responsavel VARCHAR(255) NULL,
    data_inicio_prevista DATE NULL,
    duracao_estimada VARCHAR(100) NULL,
    orcamento DECIMAL(15,2) NULL,
    descricao TEXT NULL,
    objetivo_geral TEXT NULL,
    texto_documento LONGTEXT NULL,
    FOREIGN KEY (fk_processamento) REFERENCES Processamento(id_processamento)
);

CREATE TABLE Vaga_Processada (
    id_vaga_processada INT AUTO_INCREMENT PRIMARY KEY,
    fk_processamento INT NOT NULL,
    id_vaga_externa INT NOT NULL,
    titulo_vaga VARCHAR(255) NULL,
    senioridade VARCHAR(50) NOT NULL,
    FOREIGN KEY (fk_processamento) REFERENCES Processamento(id_processamento),
    UNIQUE (fk_processamento, id_vaga_externa)
);

CREATE TABLE Vaga_Competencia (
    id_vaga_competencia INT AUTO_INCREMENT PRIMARY KEY,
    fk_vaga_processada INT NOT NULL,
    nome_competencia VARCHAR(255) NOT NULL,
    categoria VARCHAR(50) NOT NULL,
    FOREIGN KEY (fk_vaga_processada) REFERENCES Vaga_Processada(id_vaga_processada)
);

CREATE TABLE Matching_Execucao (
    id_matching_execucao INT AUTO_INCREMENT PRIMARY KEY,
    fk_processamento INT NOT NULL,
    quantidade_vagas_solicitada INT NOT NULL,
    vagas_processadas INT NOT NULL,
    fonte_dados VARCHAR(100) NULL,
    FOREIGN KEY (fk_processamento) REFERENCES Processamento(id_processamento)
);

CREATE TABLE Matching_Execucao_Vaga (
    id_matching_execucao_vaga INT AUTO_INCREMENT PRIMARY KEY,
    fk_matching_execucao INT NOT NULL,
    fk_vaga_processada INT NOT NULL,
    titulo_vaga VARCHAR(255) NULL,
    senioridade_vaga VARCHAR(50) NULL,
    status VARCHAR(50) NOT NULL,
    observacao_status TEXT NULL,
    FOREIGN KEY (fk_matching_execucao) REFERENCES Matching_Execucao(id_matching_execucao),
    FOREIGN KEY (fk_vaga_processada) REFERENCES Vaga_Processada(id_vaga_processada)
);

CREATE TABLE Candidato_Ranqueado (
    id_candidato_ranqueado INT AUTO_INCREMENT PRIMARY KEY,
    fk_matching_execucao_vaga INT NOT NULL,
    id_profissional_externo VARCHAR(100) NOT NULL,
    nome VARCHAR(255) NULL,
    senioridade VARCHAR(50) NULL,
    posicao_ranking INT NOT NULL,
    score_total DECIMAL(10,2) NOT NULL,
    justificativa_curta TEXT NULL,
    FOREIGN KEY (fk_matching_execucao_vaga) REFERENCES Matching_Execucao_Vaga(id_matching_execucao_vaga)
);

CREATE TABLE Candidato_Score_Detalhado (
    id_score_detalhado INT AUTO_INCREMENT PRIMARY KEY,
    fk_candidato_ranqueado INT NOT NULL,
    score_core INT NOT NULL DEFAULT 0,
    score_correlatas INT NOT NULL DEFAULT 0,
    score_suporte INT NOT NULL DEFAULT 0,
    score_complementares INT NOT NULL DEFAULT 0,
    FOREIGN KEY (fk_candidato_ranqueado) REFERENCES Candidato_Ranqueado(id_candidato_ranqueado),
    UNIQUE (fk_candidato_ranqueado)
);

CREATE TABLE Candidato_Competencia_Match (
    id_candidato_competencia_match INT AUTO_INCREMENT PRIMARY KEY,
    fk_candidato_ranqueado INT NOT NULL,
    nome_competencia VARCHAR(255) NOT NULL,
    categoria VARCHAR(50) NOT NULL,
    FOREIGN KEY (fk_candidato_ranqueado) REFERENCES Candidato_Ranqueado(id_candidato_ranqueado)
);

CREATE TABLE Candidato_Lacuna (
    id_candidato_lacuna INT AUTO_INCREMENT PRIMARY KEY,
    fk_candidato_ranqueado INT NOT NULL,
    nome_competencia VARCHAR(255) NOT NULL,
    FOREIGN KEY (fk_candidato_ranqueado) REFERENCES Candidato_Ranqueado(id_candidato_ranqueado)
);

-- Inserts de exemplo para o schema NOCTUA
-- Pelo menos 3 inserts por tabela
USE NOCTUA;
SET FOREIGN_KEY_CHECKS = 0;

-- Processamento
INSERT INTO Processamento (id_processamento, quantidade_consultores, senioridades_selecionadas, nome_arquivo_pdf, dt_processamento) VALUES
(1, 5, '["Pleno","Sênior"]', 'projeto_alpha.pdf', '2026-10-01 09:00:00'),
(2, 3, '["Júnior","Pleno"]', 'projeto_beta.pdf', '2026-10-05 10:30:00'),
(3, 8, '["Sênior","Especialista"]', 'projeto_gamma.pdf', '2026-10-10 14:15:00');

-- Processamento_Log_JSON
INSERT INTO Processamento_Log_JSON (id_log, fk_processamento, etapa, conteudo, dt_inclusao) VALUES
(1, 1, 'upload', '{"status":"ok","tamanho":102400}', '2026-10-01 09:01:00'),
(2, 1, 'parse', '{"paginas":12,"erros":0}', '2026-10-01 09:02:30'),
(3, 2, 'upload', '{"status":"ok","tamanho":204800}', '2026-10-05 10:31:00');

-- Documento_Projeto
INSERT INTO Documento_Projeto (id_documento, fk_processamento, nome_projeto, cliente, gestor_responsavel, data_inicio_prevista, duracao_estimada, orcamento, descricao, objetivo_geral, texto_documento) VALUES
(1, 1, 'Alpha Platform', 'Cliente A', 'Maria Silva', '2027-01-10', '6 meses', 150000.00, 'Plataforma de automação', 'Entregar MVP', 'Texto completo do documento...'),
(2, 2, 'Beta Integration', 'Cliente B', 'João Pereira', '2027-02-01', '3 meses', 60000.00, 'Integração entre serviços', 'Reduzir latência', 'Conteúdo do projeto Beta...'),
(3, 3, 'Gamma Analytics', 'Cliente C', 'Ana Costa', '2027-03-15', '12 meses', 350000.00, 'Data analytics e pipelines', 'Criar dashboards avançados', 'Documento Gamma...');

-- Vaga_Processada
INSERT INTO Vaga_Processada (id_vaga_processada, fk_processamento, id_vaga_externa, titulo_vaga, senioridade) VALUES
(1, 1, 1001, 'Desenvolvedor Backend', 'Pleno'),
(2, 1, 1002, 'Engenheiro DevOps', 'Sênior'),
(3, 1, 1003, 'Analista QA', 'Pleno'),
(4, 2, 2001, 'Front-end React', 'Júnior'),
(5, 2, 2002, 'Product Owner', 'Pleno'),
(6, 2, 2003, 'Scrum Master', 'Pleno'),
(7, 3, 3001, 'Data Engineer', 'Sênior'),
(8, 3, 3002, 'Cientista de Dados', 'Especialista'),
(9, 3, 3003, 'Arquiteto de Software', 'Sênior');

-- Vaga_Competencia
INSERT INTO Vaga_Competencia (id_vaga_competencia, fk_vaga_processada, nome_competencia, categoria) VALUES
(1, 1, 'Java', 'Core'),
(2, 1, 'MySQL', 'Correlata'),
(3, 2, 'Kubernetes', 'Core'),
(4, 3, 'Automação de Testes', 'Core'),
(5, 4, 'React', 'Core'),
(6, 5, 'Gestão de Produto', 'Suporte'),
(7, 7, 'Python', 'Core'),
(8, 8, 'Modelagem Estatística', 'Complementares'),
(9, 9, 'Design de Arquitetura', 'Core');

-- Matching_Execucao
INSERT INTO Matching_Execucao (id_matching_execucao, fk_processamento, quantidade_vagas_solicitada, vagas_processadas, fonte_dados) VALUES
(1, 1, 3, 3, 'PortalX'),
(2, 2, 2, 3, 'LinkedIn'),
(3, 3, 4, 3, 'BaseInterna');

-- Matching_Execucao_Vaga
INSERT INTO Matching_Execucao_Vaga (id_matching_execucao_vaga, fk_matching_execucao, fk_vaga_processada, titulo_vaga, senioridade_vaga, status, observacao_status) VALUES
(1, 1, 1, 'Desenvolvedor Backend', 'Pleno', 'aberto', 'Prioridade alta'),
(2, 1, 2, 'Engenheiro DevOps', 'Sênior', 'aberto', 'Precisa ter certificação'),
(3, 2, 4, 'Front-end React', 'Júnior', 'fechado', 'Contratado em 2026-09-20'),
(4, 2, 5, 'Product Owner', 'Pleno', 'aberto', NULL),
(5, 3, 7, 'Data Engineer', 'Sênior', 'aberto', 'Perfil raro'),
(6, 3, 8, 'Cientista de Dados', 'Especialista', 'aberto', 'Alocar orçamento');

-- Candidato_Ranqueado
INSERT INTO Candidato_Ranqueado (id_candidato_ranqueado, fk_matching_execucao_vaga, id_profissional_externo, nome, senioridade, posicao_ranking, score_total, justificativa_curta) VALUES
(1, 1, 'P1001', 'Carlos Souza', 'Pleno', 1, 95.50, 'Excelente fit'),
(2, 1, 'P1002', 'Mariana Lima', 'Pleno', 2, 88.00, 'Boa experiência'),
(3, 2, 'P2001', 'Lucas Rocha', 'Sênior', 1, 92.25, 'Certificações relevantes'),
(4, 3, 'P3001', 'Fernanda Dias', 'Júnior', 1, 85.00, 'Crescimento rápido'),
(5, 4, 'P4001', 'Roberto Alves', 'Pleno', 1, 78.75, 'Experiência mínima'),
(6, 5, 'P5001', 'Patrícia Gomes', 'Sênior', 1, 90.00, 'Muito experiente'),
(7, 6, 'P6001', 'Diego Fernandes', 'Especialista', 1, 93.40, 'Alto background técnico'),
(8, 4, 'P4002', 'Sofia Andrade', 'Pleno', 2, 74.10, 'Boa comunicação'),
(9, 5, 'P5002', 'Bruno Martins', 'Sênior', 2, 81.00, 'Alinhamento de competências');

-- Candidato_Score_Detalhado (pelo menos 3 registros)
INSERT INTO Candidato_Score_Detalhado (id_score_detalhado, fk_candidato_ranqueado, score_core, score_correlatas, score_suporte, score_complementares) VALUES
(1, 1, 60, 20, 10, 5),
(2, 2, 55, 18, 10, 5),
(3, 3, 62, 20, 6, 4);

-- Candidato_Competencia_Match
INSERT INTO Candidato_Competencia_Match (id_candidato_competencia_match, fk_candidato_ranqueado, nome_competencia, categoria) VALUES
(1, 1, 'Java', 'Core'),
(2, 1, 'Spring Boot', 'Correlata'),
(3, 2, 'MySQL', 'Correlata'),
(4, 3, 'Kubernetes', 'Core'),
(5, 4, 'React', 'Core'),
(6, 5, 'Gestão de Produto', 'Suporte');

-- Candidato_Lacuna
INSERT INTO Candidato_Lacuna (id_candidato_lacuna, fk_candidato_ranqueado, nome_competencia) VALUES
(1, 1, 'Docker'),
(2, 2, 'Testes Automatizados'),
(3, 3, 'Infra como Código');

SET FOREIGN_KEY_CHECKS = 1;

-- Projetos fictícios adicionais, com vagas e rankings completos.
-- Os novos registros são inseridos em ordem de dependência, com FKs habilitadas.
START TRANSACTION;

INSERT INTO Processamento (id_processamento, quantidade_consultores, senioridades_selecionadas, nome_arquivo_pdf, dt_processamento) VALUES
(4, 2, '["Pleno","Sênior"]', 'delta_commerce.pdf', '2026-08-03 09:00:00'),
(5, 2, '["Sênior","Especialista"]', 'epsilon_cloud.pdf', '2026-08-17 10:00:00'),
(6, 2, '["Pleno","Sênior"]', 'zeta_health.pdf', '2026-09-07 11:00:00'),
(7, 2, '["Júnior","Pleno"]', 'eta_experience.pdf', '2026-09-21 14:00:00'),
(8, 2, '["Sênior","Especialista"]', 'theta_intelligence.pdf', '2026-10-26 15:00:00');

INSERT INTO Processamento_Log_JSON (id_log, fk_processamento, etapa, conteudo, dt_inclusao) VALUES
(4, 4, 'upload', '{"status":"ok","tamanho":184320}', '2026-08-03 09:01:00'),
(5, 4, 'parse', '{"paginas":9,"erros":0,"vagas_identificadas":2}', '2026-08-03 09:02:00'),
(6, 4, 'matching', '{"status":"concluido","vagas_processadas":2,"candidatos_ranqueados":4}', '2026-08-03 09:03:00'),
(7, 5, 'upload', '{"status":"ok","tamanho":245760}', '2026-08-17 10:01:00'),
(8, 5, 'parse', '{"paginas":14,"erros":0,"vagas_identificadas":2}', '2026-08-17 10:02:00'),
(9, 5, 'matching', '{"status":"concluido","vagas_processadas":2,"candidatos_ranqueados":4}', '2026-08-17 10:03:00'),
(10, 6, 'upload', '{"status":"ok","tamanho":163840}', '2026-09-07 11:01:00'),
(11, 6, 'parse', '{"paginas":8,"erros":0,"vagas_identificadas":2}', '2026-09-07 11:02:00'),
(12, 6, 'matching', '{"status":"concluido","vagas_processadas":2,"candidatos_ranqueados":4}', '2026-09-07 11:03:00'),
(13, 7, 'upload', '{"status":"ok","tamanho":122880}', '2026-09-21 14:01:00'),
(14, 7, 'parse', '{"paginas":6,"erros":0,"vagas_identificadas":2}', '2026-09-21 14:02:00'),
(15, 7, 'matching', '{"status":"concluido","vagas_processadas":2,"candidatos_ranqueados":4}', '2026-09-21 14:03:00'),
(16, 8, 'upload', '{"status":"ok","tamanho":286720}', '2026-10-26 15:01:00'),
(17, 8, 'parse', '{"paginas":16,"erros":0,"vagas_identificadas":2}', '2026-10-26 15:02:00'),
(18, 8, 'matching', '{"status":"concluido","vagas_processadas":2,"candidatos_ranqueados":4}', '2026-10-26 15:03:00');

INSERT INTO Documento_Projeto (id_documento, fk_processamento, nome_projeto, cliente, gestor_responsavel, data_inicio_prevista, duracao_estimada, orcamento, descricao, objetivo_geral, texto_documento) VALUES
(4, 4, 'Delta Commerce', 'Varejo Aurora', 'Beatriz Oliveira', '2026-09-01', '5 meses', 220000.00, 'Modernização da jornada de compras e do catálogo digital.', 'Reduzir o abandono de carrinho e melhorar o tempo de resposta.', 'Construir APIs de catálogo em Java e Spring Boot e uma interface de compras em React. A equipe terá dois consultores e integração com o catálogo existente.'),
(5, 5, 'Epsilon Cloud', 'Logística Horizonte', 'Rafael Mendes', '2026-09-15', '9 meses', 480000.00, 'Migração de serviços logísticos para uma arquitetura em nuvem.', 'Automatizar a infraestrutura e ampliar a disponibilidade dos serviços.', 'Planejar a arquitetura AWS e automatizar ambientes com Terraform. Implantar serviços em Kubernetes, com observabilidade e procedimentos de recuperação.'),
(6, 6, 'Zeta Health', 'Clínicas Bem Viver', 'Camila Ribeiro', '2026-10-01', '4 meses', 175000.00, 'Integração de agendamentos e automação dos testes do portal clínico.', 'Diminuir falhas de integração e retrabalho no atendimento.', 'Desenvolver integrações em Python com PostgreSQL e testes automatizados em Cypress. Validar APIs e fluxos de agendamento com dados fictícios.'),
(7, 7, 'Eta Experience', 'Educação Farol', 'Gustavo Santos', '2026-11-09', '3 meses', 95000.00, 'Redesenho da experiência de aprendizagem em dispositivos móveis.', 'Melhorar a acessibilidade e a conclusão das trilhas de estudo.', 'Prototipar jornadas no Figma e implementar componentes React responsivos. Realizar pesquisa com usuários e validar critérios de acessibilidade.'),
(8, 8, 'Theta Intelligence', 'Energia Horizonte', 'Helena Martins', '2026-12-01', '10 meses', 620000.00, 'Plataforma analítica para previsão de consumo e indicadores operacionais.', 'Disponibilizar previsões de demanda e indicadores confiáveis.', 'Construir pipelines de dados com Apache Spark e SQL e modelos preditivos em Python. Monitorar a qualidade dos dados e o desempenho dos modelos em produção.');

INSERT INTO Vaga_Processada (id_vaga_processada, fk_processamento, id_vaga_externa, titulo_vaga, senioridade) VALUES
(10, 4, 4001, 'Desenvolvedor Java', 'Sênior'),
(11, 4, 4002, 'Desenvolvedor React', 'Pleno'),
(12, 5, 5001, 'Arquiteto Cloud', 'Especialista'),
(13, 5, 5002, 'Engenheiro de Plataforma', 'Sênior'),
(14, 6, 6001, 'Desenvolvedor de Integrações', 'Sênior'),
(15, 6, 6002, 'Analista de Qualidade', 'Pleno'),
(16, 7, 7001, 'Designer de Produto', 'Pleno'),
(17, 7, 7002, 'Desenvolvedor Front-end', 'Júnior'),
(18, 8, 8001, 'Engenheiro de Dados', 'Sênior'),
(19, 8, 8002, 'Especialista em Machine Learning', 'Especialista');

INSERT INTO Vaga_Competencia (id_vaga_competencia, fk_vaga_processada, nome_competencia, categoria) VALUES
(10, 10, 'Java', 'Core'),
(11, 10, 'Spring Boot', 'Correlata'),
(12, 10, 'Docker', 'Suporte'),
(13, 11, 'React', 'Core'),
(14, 11, 'TypeScript', 'Correlata'),
(15, 11, 'Cypress', 'Suporte'),
(16, 12, 'AWS', 'Core'),
(17, 12, 'Terraform', 'Correlata'),
(18, 12, 'FinOps', 'Complementares'),
(19, 13, 'Kubernetes', 'Core'),
(20, 13, 'Prometheus', 'Correlata'),
(21, 13, 'Argo CD', 'Suporte'),
(22, 14, 'Python', 'Core'),
(23, 14, 'PostgreSQL', 'Correlata'),
(24, 14, 'HL7 FHIR', 'Complementares'),
(25, 15, 'Cypress', 'Core'),
(26, 15, 'Testes de API', 'Correlata'),
(27, 15, 'k6', 'Suporte'),
(28, 16, 'Figma', 'Core'),
(29, 16, 'Pesquisa com Usuários', 'Correlata'),
(30, 16, 'Acessibilidade', 'Suporte'),
(31, 17, 'React', 'Core'),
(32, 17, 'CSS', 'Correlata'),
(33, 17, 'Jest', 'Suporte'),
(34, 18, 'Apache Spark', 'Core'),
(35, 18, 'SQL', 'Correlata'),
(36, 18, 'Apache Airflow', 'Suporte'),
(37, 19, 'Python', 'Core'),
(38, 19, 'Modelagem Estatística', 'Correlata'),
(39, 19, 'MLflow', 'Suporte');

INSERT INTO Matching_Execucao (id_matching_execucao, fk_processamento, quantidade_vagas_solicitada, vagas_processadas, fonte_dados) VALUES
(4, 4, 2, 2, 'BaseInterna'),
(5, 5, 2, 2, 'BaseInterna'),
(6, 6, 2, 2, 'BaseInterna'),
(7, 7, 2, 2, 'BaseInterna'),
(8, 8, 2, 2, 'BaseInterna');

INSERT INTO Matching_Execucao_Vaga (id_matching_execucao_vaga, fk_matching_execucao, fk_vaga_processada, titulo_vaga, senioridade_vaga, status, observacao_status) VALUES
(7, 4, 10, 'Desenvolvedor Java', 'Sênior', 'fechado', 'Alocação concluída em 2026-08-24.'),
(8, 4, 11, 'Desenvolvedor React', 'Pleno', 'fechado', 'Alocação concluída em 2026-08-25.'),
(9, 5, 12, 'Arquiteto Cloud', 'Especialista', 'fechado', 'Alocação concluída em 2026-09-08.'),
(10, 5, 13, 'Engenheiro de Plataforma', 'Sênior', 'aberto', 'Substituição de consultor; priorizar experiência em observabilidade.'),
(11, 6, 14, 'Desenvolvedor de Integrações', 'Sênior', 'fechado', 'Alocação concluída em 2026-09-28.'),
(12, 6, 15, 'Analista de Qualidade', 'Pleno', 'aberto', 'Reforço para a etapa de testes integrados.'),
(13, 7, 16, 'Designer de Produto', 'Pleno', 'aberto', 'Entrevistas de portfólio em andamento.'),
(14, 7, 17, 'Desenvolvedor Front-end', 'Júnior', 'aberto', 'Vaga com acompanhamento técnico de profissional pleno.'),
(15, 8, 18, 'Engenheiro de Dados', 'Sênior', 'aberto', 'Experiência em pipelines de grande volume.'),
(16, 8, 19, 'Especialista em Machine Learning', 'Especialista', 'aberto', 'Avaliar experiência em previsão de séries temporais.');

INSERT INTO Candidato_Ranqueado (id_candidato_ranqueado, fk_matching_execucao_vaga, id_profissional_externo, nome, senioridade, posicao_ranking, score_total, justificativa_curta) VALUES
(10, 7, 'P7001', 'André Nascimento', 'Sênior', 1, 94.00, 'Experiência sólida em APIs Java e serviços de comércio digital.'),
(11, 7, 'P7002', 'Juliana Teixeira', 'Sênior', 2, 86.00, 'Domínio de Spring Boot e integração com catálogos.'),
(12, 8, 'P8001', 'Renata Barros', 'Pleno', 1, 91.00, 'Experiência com interfaces React e tipagem em TypeScript.'),
(13, 8, 'P8002', 'Felipe Azevedo', 'Pleno', 2, 82.00, 'Boa experiência em componentes reutilizáveis para varejo.'),
(14, 9, 'P9001', 'Eduardo Cavalcanti', 'Especialista', 1, 96.00, 'Liderou migrações AWS com infraestrutura como código.'),
(15, 9, 'P9002', 'Larissa Monteiro', 'Especialista', 2, 89.00, 'Experiência em arquitetura resiliente e automação Terraform.'),
(16, 10, 'P10001', 'Thiago Cardoso', 'Sênior', 1, 92.00, 'Opera clusters Kubernetes com métricas e alertas Prometheus.'),
(17, 10, 'P10002', 'Isabela Freitas', 'Sênior', 2, 84.00, 'Experiência em plataformas de containers e observabilidade.'),
(18, 11, 'P11001', 'Marcelo Duarte', 'Sênior', 1, 93.00, 'Desenvolveu integrações Python com bancos PostgreSQL.'),
(19, 11, 'P11002', 'Priscila Ramos', 'Sênior', 2, 85.00, 'Experiência em APIs e consistência de dados transacionais.'),
(20, 12, 'P12001', 'Aline Moreira', 'Pleno', 1, 90.00, 'Automação de jornadas e testes de API com boa cobertura.'),
(21, 12, 'P12002', 'Vinícius Lopes', 'Pleno', 2, 80.00, 'Experiência com Cypress e validação de integrações.'),
(22, 13, 'P13001', 'Natália Campos', 'Pleno', 1, 89.00, 'Portfólio de produtos educacionais apoiado em pesquisa.'),
(23, 13, 'P13002', 'Caio Batista', 'Pleno', 2, 81.00, 'Boa experiência em prototipação e entrevistas com usuários.'),
(24, 14, 'P14001', 'Letícia Correia', 'Júnior', 1, 84.00, 'Projetos React com layouts responsivos e CSS organizado.'),
(25, 14, 'P14002', 'Pedro Farias', 'Júnior', 2, 75.00, 'Fundamentos de React e experiência inicial em interfaces móveis.'),
(26, 15, 'P15001', 'Daniela Peixoto', 'Sênior', 1, 95.00, 'Experiência em processamento distribuído com Spark e SQL.'),
(27, 15, 'P15002', 'Ricardo Tavares', 'Sênior', 2, 87.00, 'Construiu pipelines analíticos com validação de qualidade.'),
(28, 16, 'P16001', 'Mônica Reis', 'Especialista', 1, 97.00, 'Modelagem de séries temporais aplicada à previsão de demanda.'),
(29, 16, 'P16002', 'Alexandre Pinto', 'Especialista', 2, 88.00, 'Experiência em modelos estatísticos e avaliação de previsões.');

-- Para os novos candidatos, o score total é a soma dos quatro componentes.
INSERT INTO Candidato_Score_Detalhado (id_score_detalhado, fk_candidato_ranqueado, score_core, score_correlatas, score_suporte, score_complementares) VALUES
(4, 10, 60, 34, 0, 0),
(5, 11, 55, 31, 0, 0),
(6, 12, 58, 33, 0, 0),
(7, 13, 52, 30, 0, 0),
(8, 14, 62, 34, 0, 0),
(9, 15, 57, 32, 0, 0),
(10, 16, 59, 33, 0, 0),
(11, 17, 54, 30, 0, 0),
(12, 18, 60, 33, 0, 0),
(13, 19, 55, 30, 0, 0),
(14, 20, 58, 32, 0, 0),
(15, 21, 51, 29, 0, 0),
(16, 22, 57, 32, 0, 0),
(17, 23, 52, 29, 0, 0),
(18, 24, 54, 30, 0, 0),
(19, 25, 48, 27, 0, 0),
(20, 26, 61, 34, 0, 0),
(21, 27, 56, 31, 0, 0),
(22, 28, 63, 34, 0, 0),
(23, 29, 57, 31, 0, 0);

INSERT INTO Candidato_Competencia_Match (id_candidato_competencia_match, fk_candidato_ranqueado, nome_competencia, categoria) VALUES
(7, 10, 'Java', 'Core'),
(8, 10, 'Spring Boot', 'Correlata'),
(9, 11, 'Java', 'Core'),
(10, 11, 'Spring Boot', 'Correlata'),
(11, 12, 'React', 'Core'),
(12, 12, 'TypeScript', 'Correlata'),
(13, 13, 'React', 'Core'),
(14, 13, 'TypeScript', 'Correlata'),
(15, 14, 'AWS', 'Core'),
(16, 14, 'Terraform', 'Correlata'),
(17, 15, 'AWS', 'Core'),
(18, 15, 'Terraform', 'Correlata'),
(19, 16, 'Kubernetes', 'Core'),
(20, 16, 'Prometheus', 'Correlata'),
(21, 17, 'Kubernetes', 'Core'),
(22, 17, 'Prometheus', 'Correlata'),
(23, 18, 'Python', 'Core'),
(24, 18, 'PostgreSQL', 'Correlata'),
(25, 19, 'Python', 'Core'),
(26, 19, 'PostgreSQL', 'Correlata'),
(27, 20, 'Cypress', 'Core'),
(28, 20, 'Testes de API', 'Correlata'),
(29, 21, 'Cypress', 'Core'),
(30, 21, 'Testes de API', 'Correlata'),
(31, 22, 'Figma', 'Core'),
(32, 22, 'Pesquisa com Usuários', 'Correlata'),
(33, 23, 'Figma', 'Core'),
(34, 23, 'Pesquisa com Usuários', 'Correlata'),
(35, 24, 'React', 'Core'),
(36, 24, 'CSS', 'Correlata'),
(37, 25, 'React', 'Core'),
(38, 25, 'CSS', 'Correlata'),
(39, 26, 'Apache Spark', 'Core'),
(40, 26, 'SQL', 'Correlata'),
(41, 27, 'Apache Spark', 'Core'),
(42, 27, 'SQL', 'Correlata'),
(43, 28, 'Python', 'Core'),
(44, 28, 'Modelagem Estatística', 'Correlata'),
(45, 29, 'Python', 'Core'),
(46, 29, 'Modelagem Estatística', 'Correlata');

INSERT INTO Candidato_Lacuna (id_candidato_lacuna, fk_candidato_ranqueado, nome_competencia) VALUES
(4, 10, 'Docker'),
(5, 11, 'Docker'),
(6, 12, 'Cypress'),
(7, 13, 'Cypress'),
(8, 14, 'FinOps'),
(9, 15, 'FinOps'),
(10, 16, 'Argo CD'),
(11, 17, 'Argo CD'),
(12, 18, 'HL7 FHIR'),
(13, 19, 'HL7 FHIR'),
(14, 20, 'k6'),
(15, 21, 'k6'),
(16, 22, 'Acessibilidade'),
(17, 23, 'Acessibilidade'),
(18, 24, 'Jest'),
(19, 25, 'Jest'),
(20, 26, 'Apache Airflow'),
(21, 27, 'Apache Airflow'),
(22, 28, 'MLflow'),
(23, 29, 'MLflow');

COMMIT;

-- Fim
