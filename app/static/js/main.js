$(document).ready(function() {
    console.log('页面DOM加载完成，开始初始化...');
    
    // 检查必要的库是否已加载
    if (typeof $ === 'undefined') {
        console.error('jQuery库未加载');
        return;
    }
    
    console.log('jQuery库已加载，版本:', $.fn.jquery);
    
    // 改进Chart.js加载检测
    function checkChartJs() {
        if (typeof Chart === 'undefined') {
            console.warn('Chart.js库未加载，尝试重新加载...');
            // 动态加载Chart.js
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
            script.onload = function() {
                console.log('Chart.js加载成功');
                // 移除警告信息
                $('.alert-warning').remove();
            };
            script.onerror = function() {
                console.error('Chart.js加载失败');
                // 显示警告信息
                if ($('.alert-warning').length === 0) {
                    $('body').prepend('<div class="alert alert-warning alert-dismissible fade show" role="alert">Chart.js库加载失败，图表功能可能不可用。<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>');
                }
            };
            document.head.appendChild(script);
            return false;
        }
        return true;
    }
    
    // 初始检查
    if (!checkChartJs()) {
        // 如果Chart.js未加载，等待一段时间后再次检查
        setTimeout(checkChartJs, 1000);
    }
    
    // DOM元素
    const uploadArea = $('#uploadArea');
    const fileInput = $('#fileInput');
    const uploadProgress = $('#uploadProgress');
    const progressBar = uploadProgress.find('.progress-bar');
    const errorAlert = $('#errorAlert');
    const errorMessage = $('#errorMessage');
    const resultCard = $('#resultCard');
    const loadingOverlay = $('#loadingOverlay');
    const downloadCsvBtn = $('#downloadCsvBtn');
    
    // 检查关键DOM元素是否存在
    console.log('DOM元素检查:');
    console.log('uploadArea:', uploadArea.length > 0 ? '找到' : '未找到');
    console.log('fileInput:', fileInput.length > 0 ? '找到' : '未找到');
    console.log('uploadProgress:', uploadProgress.length > 0 ? '找到' : '未找到');
    console.log('errorAlert:', errorAlert.length > 0 ? '找到' : '未找到');
    console.log('resultCard:', resultCard.length > 0 ? '找到' : '未找到');
    console.log('loadingOverlay:', loadingOverlay.length > 0 ? '找到' : '未找到');
    
    // 全局变量
    let analysisData = null;
    let chart = null;
    
    // 拖放文件处理
    uploadArea.on('dragover', function(e) {
        e.preventDefault();
        e.stopPropagation();
        $(this).addClass('dragover');
    });
    
    uploadArea.on('dragleave', function(e) {
        e.preventDefault();
        e.stopPropagation();
        $(this).removeClass('dragover');
    });
    
    uploadArea.on('drop', function(e) {
        e.preventDefault();
        e.stopPropagation();
        $(this).removeClass('dragover');
        
        const files = e.originalEvent.dataTransfer.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    });
    
    // 点击上传区域触发文件选择 - 修复事件处理
    uploadArea.on('click', function(e) {
        // 检查点击是否在label元素上，如果是则不触发文件选择
        if ($(e.target).is('label') || $(e.target).closest('label').length > 0) {
            return;
        }
        
        // 检查点击是否在按钮上，如果是则不触发文件选择
        if ($(e.target).is('button') || $(e.target).closest('button').length > 0) {
            return;
        }
        
        // 检查点击是否在input元素上，如果是则不触发文件选择
        if ($(e.target).is('input') || $(e.target).closest('input').length > 0) {
            return;
        }
        
        // 触发文件选择
        fileInput.trigger('click');
    });
    
    // 文件选择变更
    fileInput.on('change', function(e) {
        console.log('文件选择变更事件触发');
        if (this.files && this.files.length > 0) {
            console.log('选择的文件:', this.files[0].name);
            handleFile(this.files[0]);
        } else {
            console.log('没有选择文件');
        }
    });
    
    // 处理选择的文件
    function handleFile(file) {
        console.log('开始处理文件:', file.name, '大小:', file.size, '类型:', file.type);
        
        // 检查文件类型
        if (!file.type.match('application/pdf')) {
            console.error('文件类型不匹配:', file.type);
            showError('只接受PDF文件');
            return;
        }
        
        // 检查文件大小 (2MB限制)
        const maxSize = 2 * 1024 * 1024; // 2MB
        if (file.size > maxSize) {
            console.error('文件过大:', file.size);
            showError('文件大小不能超过2MB');
            return;
        }
        
        // 重置UI状态
        resetUI();
        
        // 显示进度条
        uploadProgress.removeClass('d-none');
        progressBar.css('width', '0%');
        
        // 创建FormData对象
        const formData = new FormData();
        formData.append('file', file);
        
        // 显示加载遮罩
        loadingOverlay.removeClass('d-none');
        
        console.log('开始上传文件到服务器...');
        
        // 发送AJAX请求
        $.ajax({
            url: '/api/analyze',
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            xhr: function() {
                const xhr = new window.XMLHttpRequest();
                xhr.upload.addEventListener('progress', function(e) {
                    if (e.lengthComputable) {
                        const percent = Math.round((e.loaded / e.total) * 100);
                        progressBar.css('width', percent + '%');
                        progressBar.attr('aria-valuenow', percent);
                        console.log('上传进度:', percent + '%');
                    }
                }, false);
                return xhr;
            },
            success: function(response) {
                console.log('服务器响应成功:', response);
                // 隐藏加载遮罩
                loadingOverlay.addClass('d-none');
                
                if (response.success) {
                    // 保存数据
                    analysisData = response.data;
                    
                    // 显示结果
                    displayResults(analysisData);
                    
                    // 显示结果卡片
                    resultCard.removeClass('d-none');
                } else {
                    showError(response.error || '处理PDF文件时出错');
                }
            },
            error: function(xhr, status, error) {
                console.error('AJAX请求失败:', status, error);
                console.error('响应状态:', xhr.status);
                console.error('响应文本:', xhr.responseText);
                
                // 隐藏加载遮罩
                loadingOverlay.addClass('d-none');
                
                let errorMsg = '服务器错误';
                try {
                    const response = JSON.parse(xhr.responseText);
                    errorMsg = response.detail || errorMsg;
                } catch (e) {
                    console.error('解析错误响应失败', e);
                }
                
                showError(errorMsg);
            }
        });
    }
    
    // 显示错误信息
    function showError(message) {
        errorMessage.text(message);
        errorAlert.removeClass('d-none');
        uploadProgress.addClass('d-none');
    }
    
    // 重置UI状态
    function resetUI() {
        errorAlert.addClass('d-none');
        resultCard.addClass('d-none');
        uploadProgress.addClass('d-none');
        fileInput.val('');
    }
    
    // 显示分析结果
    function displayResults(data) {
        // 基本数据
        $('#spBet').text(data.sp_bet || '-');
        $('#mpBet').text(data.mp_bet || '-');
        $('#totalPoreVol').text(data.total_pore_vol || '-');
        $('#avgPoreD').text(data.avg_pore_d || '-');
        $('#mostProbable').text(data.most_probable || '-');
        $('#d90d10Ratio').text(data.d90_d10_ratio ? data.d90_d10_ratio.toFixed(4) : '-');
        
        // 高级分析数据
        $('#d10').text(data.d10 ? data.d10.toFixed(4) : '-');
        $('#d90').text(data.d90 ? data.d90.toFixed(4) : '-');
        $('#poreVolumeA').text(data.pore_volume_A ? data.pore_volume_A.toFixed(6) : '-');
        $('#d05').text(data.d0_5 ? data.d0_5.toFixed(4) : '-');
        $('#lessThan05D').text(data.less_than_0_5D ? data.less_than_0_5D.toFixed(2) : '-');
        $('#greaterThan15D').text(data.greater_than_1_5D ? data.greater_than_1_5D.toFixed(2) : '-');
        
        // 填充表格数据
        const tableBody = $('#nldftTableBody');
        tableBody.empty();
        
        if (data.nldft_data && data.nldft_data.length > 0) {
            data.nldft_data.forEach((item, index) => {
                tableBody.append(`
                    <tr>
                        <td>${index + 1}</td>
                        <td>${item.average_pore_diameter.toFixed(6)}</td>
                        <td>${item.pore_integral_volume.toFixed(6)}</td>
                    </tr>
                `);
            });
            
            // 创建图表 - 添加错误处理
            try {
                createChart(data.nldft_data);
            } catch (error) {
                console.error('创建图表时出错:', error);
                // 在图表区域显示错误信息
                const chartContainer = document.querySelector('#chart .chart-container');
                if (chartContainer) {
                    chartContainer.innerHTML = '<div class="alert alert-warning">图表加载失败，请刷新页面重试</div>';
                }
            }
        } else {
            console.warn('没有NLDFT数据可用于创建图表');
        }
    }
    
    // 创建图表
    function createChart(nldftData) {
        // 检查Chart.js是否已加载
        if (typeof Chart === 'undefined') {
            console.error('Chart.js库未加载，尝试重新加载...');
            checkChartJs();
            // 延迟创建图表
            setTimeout(() => {
                if (typeof Chart !== 'undefined') {
                    createChart(nldftData);
                } else {
                    console.error('Chart.js加载失败，无法创建图表');
                    const chartContainer = document.querySelector('#chart .chart-container');
                    if (chartContainer) {
                        chartContainer.innerHTML = '<div class="alert alert-warning">图表加载失败，请刷新页面重试</div>';
                    }
                }
            }, 2000);
            return;
        }
        
        const ctx = document.getElementById('nldftChart');
        if (!ctx) {
            console.error('找不到图表画布元素');
            return;
        }
        
        const canvas = ctx.getContext('2d');
        
        // 如果已有图表，销毁它
        if (chart) {
            chart.destroy();
        }
        
        // 准备数据
        const labels = nldftData.map(item => item.average_pore_diameter);
        const volumes = nldftData.map(item => item.pore_integral_volume);
        
        // 创建新图表
        chart = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: '孔积分体积 (cm³/g)',
                    data: volumes,
                    borderColor: '#3498db',
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    fill: true,
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        type: 'linear',
                        position: 'bottom',
                        title: {
                            display: true,
                            text: '平均孔直径 (nm)'
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: '孔积分体积 (cm³/g)'
                        }
                    }
                },
                plugins: {
                    tooltip: {
                        mode: 'index',
                        intersect: false
                    },
                    legend: {
                        position: 'top',
                    },
                    title: {
                        display: true,
                        text: 'NLDFT孔径分布'
                    }
                }
            }
        });
    }
    
    // 下载CSV数据
    downloadCsvBtn.on('click', function() {
        if (!analysisData || !analysisData.nldft_data || analysisData.nldft_data.length === 0) {
            return;
        }
        
        // 创建CSV内容
        let csvContent = "data:text/csv;charset=utf-8,";
        csvContent += "average_pore_diameter_nm,pore_integral_volume_cm3_per_g_STP\n";
        
        analysisData.nldft_data.forEach(item => {
            csvContent += `${item.average_pore_diameter.toFixed(6)},${item.pore_integral_volume.toFixed(6)}\n`;
        });
        
        // 创建下载链接
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", "nldft_data.csv");
        document.body.appendChild(link);
        
        // 触发下载
        link.click();
        
        // 清理
        document.body.removeChild(link);
    });
});

