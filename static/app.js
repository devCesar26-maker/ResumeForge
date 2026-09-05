function appData() {
    return {
        file: null,
        isDragging: false,
        inputMode: 'text',
        jobUrl: '',
        jobText: '',
        isScraping: false,
        isAnalyzing: false,
        isGeneratingResume: false,
        isGeneratingLetter: false,
        matchResult: null,
        sessionData: null,
        generatedResume: null,
        generatedLetter: null,
        generationMessage: 'Preparando documentos...',
        generationMessages: [
            'Preparando documentos...',
            'Analisando seu currículo...',
            'Reescrevendo experiências para o ATS...',
            'Escrevendo carta de apresentação...',
            'Gerando arquivo Word...',
            'Quase lá...'
        ],
        letterMessages: [
            'Preparando carta...',
            'Selecionando seus pontos fortes...',
            'Escrevendo carta de apresentação...',
            'Revisando tom e linguagem...',
            'Quase lá...'
        ],
        generationTimer: null,

        handleFileSelect(event) {
            const files = event.target.files;
            if (files.length > 0) {
                this.file = files[0];
            }
        },

        handleDrop(event) {
            this.isDragging = false;
            const files = event.dataTransfer.files;
            if (files.length > 0) {
                this.file = files[0];
            }
        },

        async scrapeJob() {
            if (!this.jobUrl) return;
            this.isScraping = true;
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 45000);
            try {
                const response = await fetch('/api/scrape', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: this.jobUrl }),
                    signal: controller.signal
                });
                const data = await response.json();
                if (response.ok) {
                    this.jobText = data.text;
                    this.inputMode = 'text'; // Alterna para a aba de texto
                } else {
                    alert('Erro ao extrair vaga: ' + data.error);
                }
            } catch (error) {
                if (error.name === 'AbortError') {
                    alert('A extração da vaga demorou demais e foi cancelada. Tente novamente.');
                } else {
                    alert('Erro de rede: ' + error.message);
                }
            } finally {
                clearTimeout(timeoutId);
                this.isScraping = false;
            }
        },

        async analyzeMatch() {
            if (!this.file || !this.jobText) return;
            
            this.isAnalyzing = true;
            this.matchResult = null;
            this.generatedResume = null;
            this.generatedLetter = null;
            
            const formData = new FormData();
            formData.append('resume', this.file);
            formData.append('job_text', this.jobText);

            // Timeout de segurança: na primeira vez (cold start do Render)
            // a análise pode demorar bem mais que o normal.
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 150000);

            try {
                const response = await fetch('/api/analyze', {
                    method: 'POST',
                    body: formData,
                    signal: controller.signal
                });
                const data = await response.json();
                
                if (response.ok) {
                    this.matchResult = data.match;
                    this.sessionData = data.session_data;
                    
                    // Desenha o gráfico Plotly após o DOM atualizar
                    setTimeout(() => this.drawRadarChart(), 100);
                } else {
                    alert('Erro na análise: ' + data.error);
                }
            } catch (error) {
                if (error.name === 'AbortError') {
                    alert('A análise demorou demais e foi cancelada. Se for a primeira vez, pode ser o cold start do servidor — tente novamente.');
                } else {
                    alert('Erro de conexão: ' + error.message);
                }
            } finally {
                clearTimeout(timeoutId);
                this.isAnalyzing = false;
            }
        },

        drawRadarChart() {
            if (!this.matchResult) return;
            
            const base = this.matchResult.score;
            const categories = ['Compatibilidade Geral', 'Experiência Relevante', 'Alinhamento Cultural', 'Potencial', 'Compatibilidade Geral'];
            
            let v1 = base;
            let v2 = this.matchResult.transferable_skills.length > 0 ? Math.min(100, base + 10) : Math.max(0, base - 10);
            let v3 = base > 60 ? 90 : 50;
            let v4 = Math.min(100, base + 15);
            
            const values = [v1, v2, v3, v4, v1];
            
            const isGood = base >= 70;
            const isOk = base >= 40 && base < 70;
            
            const fillColor = isGood ? 'rgba(34, 197, 94, 0.4)' : isOk ? 'rgba(234, 179, 8, 0.4)' : 'rgba(239, 68, 68, 0.4)';
            const lineColor = isGood ? '#22c55e' : isOk ? '#eab308' : '#ef4444';

            const data = [{
                type: 'scatterpolar',
                r: values,
                theta: categories,
                fill: 'toself',
                fillcolor: fillColor,
                line: { color: lineColor, width: 2 },
                name: 'Seu Perfil',
                hoverinfo: 'none'
            }];

            const layout = {
                polar: {
                    radialaxis: {
                        visible: true,
                        range: [0, 100],
                        showticklabels: false
                    }
                },
                showlegend: false,
                margin: { l: 30, r: 30, t: 30, b: 30 },
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                autosize: true
            };
            
            const config = { responsive: true, displayModeBar: false };

            Plotly.newPlot('radarChart', data, layout, config);
        },

        async generateResume() {
            if (!this.sessionData) return;
            
            this.isGeneratingResume = true;
            this.generatedResume = null;
            this.generatedLetter = null;
            
            // Feedback de progresso rotativo: o usuário não acha que travou
            this.generationMessage = this.generationMessages[0];
            let step = 0;
            this.generationTimer = setInterval(() => {
                step = (step + 1) % this.generationMessages.length;
                this.generationMessage = this.generationMessages[step];
            }, 10000);

            // Timeout de segurança: geração + cold start do Render pode passar de 60s
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 150000);

            try {
                const response = await fetch('/api/generate-resume', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.sessionData),
                    signal: controller.signal
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    this.generatedResume = data;
                } else {
                    alert('Erro ao gerar currículo: ' + data.error);
                }
            } catch (error) {
                if (error.name === 'AbortError') {
                    alert('A geração demorou demais e foi cancelada. Se for a primeira vez, pode ser o cold start do servidor — tente novamente.');
                } else {
                    alert('Erro de conexão: ' + error.message);
                }
            } finally {
                clearTimeout(timeoutId);
                clearInterval(this.generationTimer);
                this.isGeneratingResume = false;
            }
        },

        async generateLetter() {
            if (!this.sessionData || !this.generatedResume) return;
            
            this.isGeneratingLetter = true;
            this.generatedLetter = null;
            
            this.generationMessage = this.letterMessages[0];
            let step = 0;
            this.generationTimer = setInterval(() => {
                step = (step + 1) % this.letterMessages.length;
                this.generationMessage = this.letterMessages[step];
            }, 10000);

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 150000);

            try {
                const response = await fetch('/api/generate-cover-letter', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.sessionData),
                    signal: controller.signal
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    this.generatedLetter = data.cover_letter;
                } else {
                    alert('Erro ao gerar carta: ' + data.error);
                }
            } catch (error) {
                if (error.name === 'AbortError') {
                    alert('A geração demorou demais e foi cancelada. Se for a primeira vez, pode ser o cold start do servidor — tente novamente.');
                } else {
                    alert('Erro de conexão: ' + error.message);
                }
            } finally {
                clearTimeout(timeoutId);
                clearInterval(this.generationTimer);
                this.isGeneratingLetter = false;
            }
        }
    }
}
