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
            if (files && files.length > 0) {
                this.file = files[0];
            }
        },

        handleDrop(event) {
            this.isDragging = false;
            const files = event.dataTransfer.files;
            if (files && files.length > 0) {
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
                    this.inputMode = 'text'; // Alterna automaticamente para a aba de texto
                } else {
                    alert(data.error || 'Não foi possível extrair o conteúdo da página informada.');
                }
            } catch (error) {
                alert('Falha na conexão com o servidor. Verifique sua internet e tente novamente.');
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
                    
                    // Garante que a div #radarChart já foi renderizada antes de desenhar
                    setTimeout(() => this.drawRadarChart(), 100);
                } else {
                    alert(data.error || 'Ocorreu um erro ao processar a análise do currículo.');
                }
            } catch (error) {
                alert('Não foi possível se conectar ao servidor. Por favor, tente novamente em instantes.');
            } finally {
                this.isAnalyzing = false;
            }
        },

        drawRadarChart() {
            if (!this.matchResult) return;
            
            const base = this.matchResult.score;
            const categories = ['Aderência Geral', 'Skills Relevantes', 'Alinhamento', 'Potencial', 'Aderência Geral'];
            
            // Lógica para distribuição de eixos no gráfico Radar
            const transferableCount = this.matchResult.transferable_skills ? this.matchResult.transferable_skills.length : 0;
            let v1 = base;
            let v2 = transferableCount > 0 ? Math.min(100, base + 10) : Math.max(0, base - 10);
            let v3 = base > 60 ? 90 : 50;
            let v4 = Math.min(100, base + 15);
            
            const values = [v1, v2, v3, v4, v1];
            
            const isGood = base >= 70;
            const isOk = base >= 40 && base < 70;
            
            const fillColor = isGood ? 'rgba(16, 185, 129, 0.2)' : isOk ? 'rgba(245, 158, 11, 0.2)' : 'rgba(239, 68, 68, 0.2)';
            const lineColor = isGood ? '#10b981' : isOk ? '#f59e0b' : '#ef4444';

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
                    bgcolor: 'rgba(0,0,0,0)',
                    angularaxis: {
                        tickfont: { size: 9, color: '#94a3b8', family: 'Plus Jakarta Sans' },
                        linecolor: '#1f293d'
                    },
                    radialaxis: {
                        visible: true,
                        range: [0, 100],
                        showticklabels: false,
                        gridcolor: 'rgba(31, 41, 61, 0.3)',
                        linecolor: 'transparent'
                    }
                },
                showlegend: false,
                margin: { l: 40, r: 40, t: 25, b: 25 },
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
                    alert(data.error || 'Ocorreu uma falha ao gerar os documentos personalizados.');
                }
            } catch (error) {
                alert('Erro de conexão ao solicitar a geração dos arquivos. Tente novamente.');
            } finally {
                this.isGenerating = false;
            }
        }
    }
}