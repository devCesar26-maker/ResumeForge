function appData() {
    return {
        file: null,
        isDragging: false,
        inputMode: 'text',
        jobUrl: '',
        jobText: '',
        isScraping: false,
        isAnalyzing: false,
        isGenerating: false,
        matchResult: null,
        sessionData: null,
        generatedFiles: null,

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
            try {
                const response = await fetch('/api/scrape', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: this.jobUrl })
                });
                const data = await response.json();
                if (response.ok) {
                    this.jobText = data.text;
                    this.inputMode = 'text'; // Alterna para a aba de texto
                } else {
                    alert('Erro ao extrair vaga: ' + data.error);
                }
            } catch (error) {
                alert('Erro de rede: ' + error.message);
            } finally {
                this.isScraping = false;
            }
        },

        async analyzeMatch() {
            if (!this.file || !this.jobText) return;
            
            this.isAnalyzing = true;
            this.matchResult = null;
            this.generatedFiles = null;
            
            const formData = new FormData();
            formData.append('resume', this.file);
            formData.append('job_text', this.jobText);

            try {
                const response = await fetch('/api/analyze', {
                    method: 'POST',
                    body: formData
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
                alert('Erro de conexão: ' + error.message);
            } finally {
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

        async generateDocs() {
            if (!this.sessionData) return;
            
            this.isGenerating = true;
            
            try {
                const response = await fetch('/api/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.sessionData)
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    this.generatedFiles = data;
                } else {
                    alert('Erro ao gerar documentos: ' + data.error);
                }
            } catch (error) {
                alert('Erro de conexão: ' + error.message);
            } finally {
                this.isGenerating = false;
            }
        }
    }
}
