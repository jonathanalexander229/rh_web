// Global variables
let optionsData = {
    open_positions: [],
    closed_positions: [],
    expired_positions: [],
    all_orders: []
};

document.addEventListener('DOMContentLoaded', function() {
    // Core elements
    const tabButtons = document.querySelectorAll('.tab');
    const tabContents = document.querySelectorAll('.tab-content');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const dashboardContent = document.getElementById('dashboardContent');
    const errorMessage = document.getElementById('errorMessage');
    
    // Tab switching
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));
            
            button.classList.add('active');
            const tabId = button.getAttribute('data-tab');
            document.getElementById(tabId).classList.add('active');
        });
    });
    
    // Fetch data from API
    function fetchOptionsData() {
        loadingIndicator.style.display = 'block';
        dashboardContent.style.display = 'none';
        errorMessage.style.display = 'none';
        
        fetch('/api/options')
            .then(response => {
                if (response.status === 401) {
                    window.location.href = '/login';
                    throw new Error('Login required');
                }
                if (!response.ok) {
                    return response.json().then(errData => {
                        throw new Error(errData.error || 'Server error');
                    });
                }
                return response.json();
            })
            .then(data => {
                if (data && data.error) {
                    throw new Error(data.error);
                }
                
                optionsData = {
                    open_positions: data.open_positions || [],
                    closed_positions: data.closed_positions || [],
                    expired_positions: data.expired_positions || [],
                    all_orders: data.all_orders || []
                };
                
                renderDashboard();
                
                loadingIndicator.style.display = 'none';
                dashboardContent.style.display = 'block';
                
                const now = new Date();
                document.getElementById('lastUpdated').textContent = 
                    `Last updated: ${now.toLocaleTimeString()}`;
            })
            .catch(error => {
                console.error('Error fetching data:', error);
                loadingIndicator.style.display = 'none';
                errorMessage.innerHTML = `Error loading data: ${error.message}<br>
                    <small>Check the console for more details</small>`;
                errorMessage.style.display = 'block';
            });
    }
    
    // Initialize dashboard
    function renderDashboard() {
        renderSummary();
        renderOpenPositions();
        renderClosedPositions();
        renderExpiredPositions();
        renderAllOrders();
        populateFilters();
        setupSortListeners(); // New sorting functionality
    }
    
    // Initial data fetch
    fetchOptionsData();
    
    // Event listener for refresh button
    document.getElementById('refreshData').addEventListener('click', fetchOptionsData);
});