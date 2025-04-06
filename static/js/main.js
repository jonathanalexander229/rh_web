// Global variables
let optionsData = {
    open_positions: [],
    closed_positions: [],
    expired_positions: [],
    all_orders: []
};

// Database snapshot variables
let snapshots = [];
let currentSnapshot = null;

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
    
    // Fetch snapshots from database
    function fetchSnapshots() {
        return fetch('/api/snapshots')
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to fetch snapshots');
                }
                return response.json();
            })
            .then(data => {
                snapshots = data;
                
                // Find the latest snapshot
                const latestSnapshot = snapshots.find(s => s.is_latest);
                currentSnapshot = latestSnapshot ? latestSnapshot.timestamp : null;
                
                return snapshots;
            });
    }
    
    // Fetch specific snapshot data
    function fetchSnapshotData(timestamp) {
        return fetch(`/api/snapshots/${timestamp}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to fetch snapshot data');
                }
                return response.json();
            });
    }
    
    // Fetch data from API
    function fetchOptionsData(fetchMode = 'auto', useCache = true) {
        loadingIndicator.style.display = 'block';
        dashboardContent.style.display = 'none';
        errorMessage.style.display = 'none';
        
        let dataPromise;
        
        if (!useCache || fetchMode !== 'auto') {
            // Force refresh from Robinhood API with specified fetch mode
            const url = `/api/options?use_cache=${useCache}&fetch_mode=${fetchMode}`;
            dataPromise = fetch(url)
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
                });
        } else {
            // Try to use cached data if available
            dataPromise = fetchSnapshots()
                .then(() => {
                    if (currentSnapshot) {
                        return fetchSnapshotData(currentSnapshot);
                    } else {
                        // No snapshots available, fetch from API with auto mode
                        return fetch('/api/options?fetch_mode=auto')
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
                            });
                    }
                });
        }
        
        dataPromise
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
                updateSnapshotSelector();
                
                loadingIndicator.style.display = 'none';
                dashboardContent.style.display = 'block';
                
                const now = new Date();
                const source = !useCache ? 'Robinhood API' : (currentSnapshot ? 'Database' : 'Robinhood API');
                let sourceDetails = source;
                if (source === 'Robinhood API' && fetchMode !== 'auto') {
                    sourceDetails = `${source} (${fetchMode} mode)`;
                }
                document.getElementById('lastUpdated').textContent = 
                    `Last updated: ${now.toLocaleTimeString()} (Source: ${sourceDetails})`;
            })
            .catch(error => {
                console.error('Error fetching data:', error);
                loadingIndicator.style.display = 'none';
                errorMessage.innerHTML = `Error loading data: ${error.message}<br>
                    <small>Check the console for more details</small>`;
                errorMessage.style.display = 'block';
            });
    }
    
    // Update the snapshot selector dropdown
    function updateSnapshotSelector() {
        const snapshotSelector = document.getElementById('snapshotSelector');
        if (!snapshotSelector) return;
        
        // Clear existing options
        snapshotSelector.innerHTML = '';
        
        // Create option for each snapshot
        snapshots.forEach(snapshot => {
            const option = document.createElement('option');
            option.value = snapshot.timestamp;
            
            // Format timestamp for display
            const date = new Date(snapshot.timestamp);
            const formattedDate = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
            
            option.textContent = `${formattedDate}${snapshot.is_latest ? ' (Latest)' : ''}`;
            
            // Select current snapshot
            if (snapshot.timestamp === currentSnapshot) {
                option.selected = true;
            }
            
            snapshotSelector.appendChild(option);
        });
    }
    
    // Load a specific snapshot when selected
    function loadSnapshot(timestamp) {
        if (!timestamp) return;
        
        currentSnapshot = timestamp;
        
        loadingIndicator.style.display = 'block';
        dashboardContent.style.display = 'none';
        
        fetchSnapshotData(timestamp)
            .then(data => {
                optionsData = {
                    open_positions: data.open_positions || [],
                    closed_positions: data.closed_positions || [],
                    expired_positions: data.expired_positions || [],
                    all_orders: data.all_orders || []
                };
                
                renderDashboard();
                
                loadingIndicator.style.display = 'none';
                dashboardContent.style.display = 'block';
                
                const snapshotDate = new Date(timestamp);
                document.getElementById('lastUpdated').textContent = 
                    `Snapshot from: ${snapshotDate.toLocaleDateString()} ${snapshotDate.toLocaleTimeString()}`;
            })
            .catch(error => {
                console.error('Error loading snapshot:', error);
                loadingIndicator.style.display = 'none';
                errorMessage.innerHTML = `Error loading snapshot: ${error.message}`;
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
    
    // Setup fetch controls
    function setupFetchControls() {
        // Add fetch mode select
        const fetchModeSelect = document.createElement('select');
        fetchModeSelect.id = 'fetchModeSelect';
        fetchModeSelect.style.marginLeft = '10px';
        fetchModeSelect.style.maxWidth = '200px';
        fetchModeSelect.innerHTML = `
            <option value="auto">Auto (Smart Fetch)</option>
            <option value="update">Update (Since Earliest Open)</option>
            <option value="initial">Initial (60 Days)</option>
            <option value="all">All History</option>
        `;
        
        // Refresh button
        const refreshButton = document.getElementById('refreshData');
        
        // Insert fetchModeSelect before refreshButton
        const refreshContainer = refreshButton.parentNode;
        refreshContainer.insertBefore(fetchModeSelect, refreshButton);
        
        // Update refresh button label
        refreshButton.textContent = 'Refresh from API';
        
        // Add event listener to refresh button
        refreshButton.addEventListener('click', () => {
            const fetchMode = document.getElementById('fetchModeSelect').value;
            fetchOptionsData(fetchMode, false); // Force refresh from API with selected mode
        });
    }
    
    // Event listener for snapshot selector
    const snapshotSelector = document.getElementById('snapshotSelector');
    if (snapshotSelector) {
        snapshotSelector.addEventListener('change', (e) => {
            loadSnapshot(e.target.value);
        });
    }
    
    // Setup fetch controls
    setupFetchControls();
});