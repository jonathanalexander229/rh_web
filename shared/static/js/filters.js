// Setup filter event listeners
function setupFilterEventListeners() {
    // Open positions filters
    document.getElementById('openSymbolFilter').addEventListener('change', filterOpenPositions);
    document.getElementById('openStrategyFilter').addEventListener('change', filterOpenPositions);
    document.getElementById('openOptionTypeFilter').addEventListener('change', filterOpenPositions);
    document.getElementById('openDateFrom').addEventListener('change', filterOpenPositions);
    document.getElementById('openDateTo').addEventListener('change', filterOpenPositions);
    document.getElementById('resetOpenFilters').addEventListener('click', resetOpenFilters);
    
    // Closed positions filters
    document.getElementById('closedSymbolFilter').addEventListener('change', filterClosedPositions);
    document.getElementById('closedStrategyFilter').addEventListener('change', filterClosedPositions);
    document.getElementById('closedDirectionFilter').addEventListener('change', filterClosedPositions);
    document.getElementById('closedProfitFilter').addEventListener('change', filterClosedPositions);
    document.getElementById('closedOpenDateFrom').addEventListener('change', filterClosedPositions);
    document.getElementById('closedOpenDateTo').addEventListener('change', filterClosedPositions);
    document.getElementById('closedCloseDateFrom').addEventListener('change', filterClosedPositions);
    document.getElementById('closedCloseDateTo').addEventListener('change', filterClosedPositions);
    document.getElementById('resetClosedFilters').addEventListener('click', resetClosedFilters);
    
    // Expired positions filters
    document.getElementById('expiredSymbolFilter').addEventListener('change', filterExpiredPositions);
    document.getElementById('expiredStrategyFilter').addEventListener('change', filterExpiredPositions);
    document.getElementById('expiredOpenDateFrom').addEventListener('change', filterExpiredPositions);
    document.getElementById('expiredOpenDateTo').addEventListener('change', filterExpiredPositions);
    document.getElementById('resetExpiredFilters').addEventListener('click', resetExpiredFilters);
    
    // All orders filters
    document.getElementById('allSymbolFilter').addEventListener('change', filterAllOrders);
    document.getElementById('allPositionFilter').addEventListener('change', filterAllOrders);
    document.getElementById('allOptionTypeFilter').addEventListener('change', filterAllOrders);
    document.getElementById('allDateFrom').addEventListener('change', filterAllOrders);
    document.getElementById('allDateTo').addEventListener('change', filterAllOrders);
    document.getElementById('resetAllFilters').addEventListener('click', resetAllFilters);
}

// Filter functions with date range filtering
function filterOpenPositions() {
    const symbolFilter = document.getElementById('openSymbolFilter').value;
    const strategyFilter = document.getElementById('openStrategyFilter').value;
    const optionTypeFilter = document.getElementById('openOptionTypeFilter').value;
    const dateFromFilter = document.getElementById('openDateFrom').value;
    const dateToFilter = document.getElementById('openDateTo').value;
    
    const rows = document.querySelectorAll('#openPositionsTable tbody tr');
    
    rows.forEach(row => {
        if (row.classList.contains('empty-message')) return;
        
        const symbol = row.dataset.symbol || '';
        const strategy = row.dataset.strategy || '';
        const optionType = row.dataset.optionType || '';
        const openDate = row.dataset.openDate || '';
        
        // Check all filter matches
        const symbolMatch = !symbolFilter || symbol === symbolFilter;
        const strategyMatch = !strategyFilter || strategy === strategyFilter;
        const optionTypeMatch = !optionTypeFilter || optionType.toLowerCase().includes(optionTypeFilter.toLowerCase());
        
        // Date range matches
        const dateFromMatch = !dateFromFilter || (openDate && openDate >= dateFromFilter);
        const dateToMatch = !dateToFilter || (openDate && openDate <= dateToFilter);
        
        row.style.display = (symbolMatch && strategyMatch && optionTypeMatch && 
                            dateFromMatch && dateToMatch) ? '' : 'none';
    });
    
    checkEmptyTable('#openPositionsTable tbody', 10);
}

function filterClosedPositions() {
    const symbolFilter = document.getElementById('closedSymbolFilter').value;
    const strategyFilter = document.getElementById('closedStrategyFilter').value;
    const directionFilter = document.getElementById('closedDirectionFilter').value;
    const profitFilter = document.getElementById('closedProfitFilter').value;
    const openDateFromFilter = document.getElementById('closedOpenDateFrom').value;
    const openDateToFilter = document.getElementById('closedOpenDateTo').value;
    const closeDateFromFilter = document.getElementById('closedCloseDateFrom').value;
    const closeDateToFilter = document.getElementById('closedCloseDateTo').value;
    
    const rows = document.querySelectorAll('#closedPositionsTable tbody tr');
    
    rows.forEach(row => {
        if (row.classList.contains('empty-message')) return;
        
        const symbol = row.dataset.symbol || '';
        const strategy = row.dataset.strategy || '';
        const netCredit = parseFloat(row.dataset.netCredit || 0);
        const openDate = row.dataset.openDate || '';
        const closeDate = row.dataset.closeDate || '';
        
        // Check all filter matches
        const symbolMatch = !symbolFilter || symbol === symbolFilter;
        const strategyMatch = !strategyFilter || strategy === strategyFilter;
        const directionMatch = !directionFilter || 
            (directionFilter === 'credit' && netCredit > 0) || 
            (directionFilter === 'debit' && netCredit <= 0);
        const profitMatch = !profitFilter || 
            (profitFilter === 'profit' && netCredit > 0) || 
            (profitFilter === 'loss' && netCredit <= 0);
        
        // Date range matches
        const openDateFromMatch = !openDateFromFilter || (openDate && openDate >= openDateFromFilter);
        const openDateToMatch = !openDateToFilter || (openDate && openDate <= openDateToFilter);
        const closeDateFromMatch = !closeDateFromFilter || (closeDate && closeDate >= closeDateFromFilter);
        const closeDateToMatch = !closeDateToFilter || (closeDate && closeDate <= closeDateToFilter);
        
        row.style.display = (symbolMatch && strategyMatch && directionMatch && profitMatch && 
                           openDateFromMatch && openDateToMatch && closeDateFromMatch && closeDateToMatch) ? '' : 'none';
    });
    
    checkEmptyTable('#closedPositionsTable tbody', 10);
}

function filterExpiredPositions() {
    const symbolFilter = document.getElementById('expiredSymbolFilter').value;
    const strategyFilter = document.getElementById('expiredStrategyFilter').value;
    const openDateFromFilter = document.getElementById('expiredOpenDateFrom').value;
    const openDateToFilter = document.getElementById('expiredOpenDateTo').value;
    
    const rows = document.querySelectorAll('#expiredPositionsTable tbody tr');
    
    rows.forEach(row => {
        if (row.classList.contains('empty-message')) return;
        
        const symbol = row.dataset.symbol || '';
        const strategy = row.dataset.strategy || '';
        const openDate = row.dataset.openDate || '';
        
        // Check all filter matches
        const symbolMatch = !symbolFilter || symbol === symbolFilter;
        const strategyMatch = !strategyFilter || strategy === strategyFilter;
        
        // Date range matches
        const openDateFromMatch = !openDateFromFilter || (openDate && openDate >= openDateFromFilter);
        const openDateToMatch = !openDateToFilter || (openDate && openDate <= openDateToFilter);
        
        row.style.display = (symbolMatch && strategyMatch && openDateFromMatch && 
                           openDateToMatch) ? '' : 'none';
    });
    
    checkEmptyTable('#expiredPositionsTable tbody', 10);
}

function filterAllOrders() {
    const symbolFilter = document.getElementById('allSymbolFilter').value;
    const positionFilter = document.getElementById('allPositionFilter').value;
    const optionTypeFilter = document.getElementById('allOptionTypeFilter').value;
    const dateFromFilter = document.getElementById('allDateFrom').value;
    const dateToFilter = document.getElementById('allDateTo').value;
    
    const rows = document.querySelectorAll('#allOrdersTable tbody tr');
    
    rows.forEach(row => {
        if (row.classList.contains('empty-message')) return;
        
        const symbol = row.dataset.symbol || '';
        const position = row.dataset.position || '';
        const optionType = row.dataset.optionType || '';
        const date = row.dataset.date || '';
        
        // Check all filter matches
        const symbolMatch = !symbolFilter || symbol === symbolFilter;
        const positionMatch = !positionFilter || position === positionFilter;
        const optionTypeMatch = !optionTypeFilter || optionType.toLowerCase().includes(optionTypeFilter.toLowerCase());
        
        // Date range matches
        const dateFromMatch = !dateFromFilter || (date && date >= dateFromFilter);
        const dateToMatch = !dateToFilter || (date && date <= dateToFilter);
        
        row.style.display = (symbolMatch && positionMatch && optionTypeMatch && 
                           dateFromMatch && dateToMatch) ? '' : 'none';
    });
    
    checkEmptyTable('#allOrdersTable tbody', 11);
}

// Reset filter functions
function resetOpenFilters() {
    document.getElementById('openSymbolFilter').value = '';
    document.getElementById('openStrategyFilter').value = '';
    document.getElementById('openOptionTypeFilter').value = '';
    document.getElementById('openDateFrom').value = '';
    document.getElementById('openDateTo').value = '';
    filterOpenPositions();
}

function resetClosedFilters() {
    document.getElementById('closedSymbolFilter').value = '';
    document.getElementById('closedStrategyFilter').value = '';
    document.getElementById('closedDirectionFilter').value = '';
    document.getElementById('closedProfitFilter').value = '';
    document.getElementById('closedOpenDateFrom').value = '';
    document.getElementById('closedOpenDateTo').value = '';
    document.getElementById('closedCloseDateFrom').value = '';
    document.getElementById('closedCloseDateTo').value = '';
    filterClosedPositions();
}

function resetExpiredFilters() {
    document.getElementById('expiredSymbolFilter').value = '';
    document.getElementById('expiredStrategyFilter').value = '';
    document.getElementById('expiredOpenDateFrom').value = '';
    document.getElementById('expiredOpenDateTo').value = '';
    filterExpiredPositions();
}

function resetAllFilters() {
    document.getElementById('allSymbolFilter').value = '';
    document.getElementById('allPositionFilter').value = '';
    document.getElementById('allOptionTypeFilter').value = '';
    document.getElementById('allDateFrom').value = '';
    document.getElementById('allDateTo').value = '';
    filterAllOrders();
}

// Helper to check if table is empty after filtering
function checkEmptyTable(selector, colSpan) {
    const tbody = document.querySelector(selector);
    let visibleRows = 0;
    
    tbody.querySelectorAll('tr').forEach(row => {
        if (row.style.display !== 'none') {
            visibleRows++;
        }
    });
    
    if (visibleRows === 0) {
        const existingEmpty = tbody.querySelector('.empty-message');
        if (existingEmpty) {
            existingEmpty.remove();
        }
        
        const emptyRow = document.createElement('tr');
        emptyRow.innerHTML = `
            <td colspan="${colSpan}" class="empty-message">No matching results found</td>
        `;
        tbody.appendChild(emptyRow);
    } else {
        const existingEmpty = tbody.querySelector('.empty-message');
        if (existingEmpty) {
            existingEmpty.remove();
        }
    }
}