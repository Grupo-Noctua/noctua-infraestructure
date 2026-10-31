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

-- Fim
