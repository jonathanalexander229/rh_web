// Table sorting state
let currentSort = {
    table: null,
    column: null,
    direction: 'asc'
};

// Setup sort listeners for table headers
function setupSortListeners() {
    document.querySelectorAll('th[data-sort]').forEach(header => {
        header.addEventListener('click', () => {
            // Get the table and sort column
            const table = header.closest('table');
            const sortColumn = header.getAttribute('data-sort');
            
            // Determine sort direction
            let direction = 'asc';
            if (currentSort.table === table.id && currentSort.column === sortColumn) {
                direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
            }
            
            // Update sort state
            currentSort = {
                table: table.id,
                column: sortColumn,
                direction: direction
            };
            
            // Remove sort classes from all headers in this table
            table.querySelectorAll('th').forEach(th => {
                th.classList.remove('sort-asc', 'sort-desc');
            });
            
            // Add sort class to the clicked header
            header.classList.add(`sort-${direction}`);
            
            // Perform sort
            sortTable(table, sortColumn, direction);
        });
    });
}

// Sort table by column
function sortTable(table, column, direction) {
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr:not(.empty-message)'));
    
    // Sort the rows based on the data attribute for the column
    rows.sort((a, b) => {
        let aValue = a.dataset[column] || '';
        let bValue = b.dataset[column] || '';
        
        // Parse dates for date columns
        if (column.includes('Date') || column === 'date') {
            aValue = aValue ? new Date(aValue) : new Date(0);
            bValue = bValue ? new Date(bValue) : new Date(0);
            
            return direction === 'asc' 
                ? aValue - bValue 
                : bValue - aValue;
        }
        
        // Parse numbers for numeric columns
        if (!isNaN(parseFloat(aValue)) && !isNaN(parseFloat(bValue))) {
            return direction === 'asc' 
                ? parseFloat(aValue) - parseFloat(bValue) 
                : parseFloat(bValue) - parseFloat(aValue);
        }
        
        // Default string comparison
        return direction === 'asc' 
            ? String(aValue).localeCompare(String(bValue)) 
            : String(bValue).localeCompare(String(aValue));
    });
    
    // Remove existing rows
    rows.forEach(row => row.remove());
    
    // Append sorted rows
    rows.forEach(row => tbody.appendChild(row));
    
    // Check for empty table
    const colCount = table.querySelector('tr').cells.length;
    checkEmptyTable(`#${table.id} tbody`, colCount);
}