// Render summary statistics
function renderSummary() {
    const summary = document.getElementById('summary');
    
    // Calculate total open value
    const openValue = optionsData.open_positions.reduce((total, position) => {
        return total + (position.open_premium || 0);
    }, 0).toFixed(2);
    
    // Calculate P&L from closed positions only
    const closedPL = optionsData.closed_positions.reduce((total, position) => {
        return total + (position.net_credit || 0);
    }, 0).toFixed(2);
    
    // Count positions
    const openCount = optionsData.open_positions.length;
    const closedCount = optionsData.closed_positions.length;
    const expiredCount = optionsData.expired_positions.length;
    
    summary.innerHTML = `
        <div class="summary-card">
            <h3>Open Positions</h3>
            <div class="value">${openCount}</div>
        </div>
        <div class="summary-card">
            <h3>Open Value</h3>
            <div class="value">$${Math.abs(openValue)}</div>
        </div>
        <div class="summary-card">
            <h3>Closed P&L</h3>
            <div class="value ${Number(closedPL) >= 0 ? 'profit' : 'loss'}">
                ${Number(closedPL) >= 0 ? '+' : ''}$${closedPL}
            </div>
        </div>
        <div class="summary-card">
            <h3>Total Trades</h3>
            <div class="value">${openCount + closedCount + expiredCount}</div>
        </div>
    `;
}

// Render open positions table with data attributes for sorting
function renderOpenPositions() {
    const tbody = document.querySelector('#openPositionsTable tbody');
    tbody.innerHTML = '';
    
    if (optionsData.open_positions.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" class="empty-message">No open positions found</td>
            </tr>
        `;
        return;
    }
    
    optionsData.open_positions.forEach(position => {
        const row = document.createElement('tr');
        const optionType = position.option_type || '';
        
        row.innerHTML = `
            <td>${position.symbol}</td>
            <td>${position.strategy || ''}</td>
            <td>${position.open_date || ''}</td>
            <td>${position.expiration_date || ''}</td>
            <td>${position.strike_price || ''}</td>
            <td>${optionType}</td>
            <td class="${position.direction}">${position.direction || ''}</td>
            <td>${position.quantity || ''}</td>
            <td>${position.open_price ? '$' + position.open_price.toFixed(2) : ''}</td>
            <td>${position.open_premium ? '$' + Math.abs(position.open_premium).toFixed(2) : ''}</td>
        `;
        
        // Add data attributes for sorting
        row.dataset.symbol = position.symbol || '';
        row.dataset.strategy = position.strategy || '';
        row.dataset.openDate = position.open_date || '';
        row.dataset.expirationDate = position.expiration_date || '';
        row.dataset.strikePrice = parseFloat(position.strike_price || 0);
        row.dataset.optionType = optionType;
        row.dataset.direction = position.direction || '';
        row.dataset.quantity = parseFloat(position.quantity || 0);
        row.dataset.openPrice = parseFloat(position.open_price || 0);
        row.dataset.openPremium = parseFloat(position.open_premium || 0);
        
        tbody.appendChild(row);
    });
}

// Render closed positions table with data attributes for sorting
function renderClosedPositions() {
    const tbody = document.querySelector('#closedPositionsTable tbody');
    tbody.innerHTML = '';
    
    if (optionsData.closed_positions.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="11" class="empty-message">No closed positions found</td>
            </tr>
        `;
        return;
    }
    
    optionsData.closed_positions.forEach(position => {
        const row = document.createElement('tr');
        
        // Determine if profit or loss
        const isProfitable = position.net_credit > 0;
        const netClass = isProfitable ? 'profit' : 'loss';
        
        row.innerHTML = `
            <td>${position.symbol}</td>
            <td>${position.strategy || ''}</td>
            <td>${position.open_date || ''}</td>
            <td>${position.close_date || ''}</td>
            <td>${position.expiration_date || ''}</td>
            <td>${position.strike_price || ''}</td>
            <td>${position.option_type || ''}</td>
            <td>${position.quantity || ''}</td>
            <td>${position.open_price ? '$' + position.open_price.toFixed(2) : ''}</td>
            <td>${position.close_price ? '$' + position.close_price.toFixed(2) : ''}</td>
            <td class="${netClass}">
                ${position.net_credit ? (isProfitable ? '+' : '') + '$' + position.net_credit.toFixed(2) : ''}
            </td>
        `;
        
        // Add data attributes for sorting
        row.dataset.symbol = position.symbol || '';
        row.dataset.strategy = position.strategy || '';
        row.dataset.openDate = position.open_date || '';
        row.dataset.closeDate = position.close_date || '';
        row.dataset.expirationDate = position.expiration_date || '';
        row.dataset.strikePrice = parseFloat(position.strike_price || 0);
        row.dataset.optionType = position.option_type || '';
        row.dataset.quantity = parseInt(position.quantity || 0);
        row.dataset.openPrice = parseFloat(position.open_price || 0);
        row.dataset.closePrice = parseFloat(position.close_price || 0);
        row.dataset.netCredit = parseFloat(position.net_credit || 0);
        
        tbody.appendChild(row);
    });
}

// Render expired positions table with data attributes for sorting
function renderExpiredPositions() {
    const tbody = document.querySelector('#expiredPositionsTable tbody');
    tbody.innerHTML = '';
    
    if (optionsData.expired_positions.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" class="empty-message">No expired positions found</td>
            </tr>
        `;
        return;
    }
    
    optionsData.expired_positions.forEach(position => {
        const row = document.createElement('tr');
        
        row.innerHTML = `
            <td>${position.symbol}</td>
            <td>${position.strategy || ''}</td>
            <td>${position.open_date || ''}</td>
            <td>${position.expiration_date || ''}</td>
            <td>${position.strike_price || ''}</td>
            <td>${position.option_type || ''}</td>
            <td class="${position.direction}">${position.direction || ''}</td>
            <td>${position.quantity || ''}</td>
            <td>${position.open_price ? '$' + position.open_price.toFixed(2) : ''}</td>
            <td>${position.open_premium ? '$' + Math.abs(position.open_premium).toFixed(2) : ''}</td>
        `;
        
        // Add data attributes for sorting
        row.dataset.symbol = position.symbol || '';
        row.dataset.strategy = position.strategy || '';
        row.dataset.openDate = position.open_date || '';
        row.dataset.expirationDate = position.expiration_date || '';
        row.dataset.strikePrice = parseFloat(position.strike_price || 0);
        row.dataset.optionType = position.option_type || '';
        row.dataset.direction = position.direction || '';
        row.dataset.quantity = parseFloat(position.quantity || 0);
        row.dataset.openPrice = parseFloat(position.open_price || 0);
        row.dataset.openPremium = parseFloat(position.open_premium || 0);
        
        tbody.appendChild(row);
    });
}

// Render all orders table with data attributes for sorting
function renderAllOrders() {
    const tbody = document.querySelector('#allOrdersTable tbody');
    tbody.innerHTML = '';
    
    if (optionsData.all_orders.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="11" class="empty-message">No orders found</td>
            </tr>
        `;
        return;
    }
    
    optionsData.all_orders.forEach(order => {
        const row = document.createElement('tr');
        
        row.innerHTML = `
            <td>${order.symbol}</td>
            <td>${order.created_at || ''}</td>
            <td>${order.position_effect || ''}</td>
            <td>${order.strategy || ''}</td>
            <td>${order.expiration_date || ''}</td>
            <td>${order.strike_price || ''}</td>
            <td>${order.option_type || ''}</td>
            <td class="${order.direction}">${order.direction || ''}</td>
            <td>${order.quantity || ''}</td>
            <td>${order.price ? '$' + order.price.toFixed(2) : ''}</td>
            <td>${order.premium ? '$' + Math.abs(order.premium).toFixed(2) : ''}</td>
        `;
        
        // Add data attributes for sorting
        row.dataset.symbol = order.symbol || '';
        row.dataset.date = order.created_at || '';
        row.dataset.position = order.position_effect || '';
        row.dataset.strategy = order.strategy || '';
        row.dataset.expirationDate = order.expiration_date || '';
        row.dataset.strikePrice = parseFloat(order.strike_price || 0);
        row.dataset.optionType = order.option_type || '';
        row.dataset.direction = order.direction || '';
        row.dataset.quantity = parseFloat(order.quantity || 0);
        row.dataset.price = parseFloat(order.price || 0);
        row.dataset.premium = parseFloat(order.premium || 0);
        
        tbody.appendChild(row);
    });
}

// Helper function to populate filter dropdowns
function populateFilters() {
    // Get unique values
    const symbols = [...new Set(optionsData.all_orders.map(order => order.symbol))].filter(Boolean).sort();
    const strategies = [...new Set([
        ...optionsData.open_positions.map(pos => pos.strategy),
        ...optionsData.closed_positions.map(pos => pos.strategy),
        ...optionsData.expired_positions.map(pos => pos.strategy)
    ])].filter(Boolean).sort();
    
    // Populate dropdowns
    populateFilterOptions('openSymbolFilter', symbols);
    populateFilterOptions('closedSymbolFilter', symbols);
    populateFilterOptions('expiredSymbolFilter', symbols);
    populateFilterOptions('allSymbolFilter', symbols);
    
    populateFilterOptions('openStrategyFilter', strategies);
    populateFilterOptions('closedStrategyFilter', strategies);
    populateFilterOptions('expiredStrategyFilter', strategies);
    
    // Set default date range values - last 3 months
    setDefaultDateRanges();
    
    // Add event listeners
    setupFilterEventListeners();
}

// Helper to set default date ranges
function setDefaultDateRanges() {
    const today = new Date();
    const threeMonthsAgo = new Date();
    threeMonthsAgo.setMonth(today.getMonth() - 3);
    
    const todayStr = today.toISOString().split('T')[0];
    const threeMonthsAgoStr = threeMonthsAgo.toISOString().split('T')[0];
    
    // Set "from" date for all date filters (optional)
    document.getElementById('openDateFrom').value = threeMonthsAgoStr;
    document.getElementById('closedOpenDateFrom').value = threeMonthsAgoStr;
    document.getElementById('closedCloseDateFrom').value = '';
    document.getElementById('expiredOpenDateFrom').value = threeMonthsAgoStr;
    document.getElementById('allDateFrom').value = threeMonthsAgoStr;
    
    // Set "to" date for all date filters
    document.getElementById('openDateTo').value = todayStr;
    document.getElementById('closedOpenDateTo').value = todayStr;
    document.getElementById('closedCloseDateTo').value = todayStr;
    document.getElementById('expiredOpenDateTo').value = todayStr;
    document.getElementById('allDateTo').value = todayStr;
}

// Helper to populate a dropdown
function populateFilterOptions(filterId, options) {
    const filter = document.getElementById(filterId);
    
    // Keep the first "All" option
    const allOption = filter.options[0];
    filter.innerHTML = '';
    filter.appendChild(allOption);
    
    // Add options
    options.forEach(option => {
        if (option) {
            const optionEl = document.createElement('option');
            optionEl.value = option;
            optionEl.textContent = option;
            filter.appendChild(optionEl);
        }
    });
}