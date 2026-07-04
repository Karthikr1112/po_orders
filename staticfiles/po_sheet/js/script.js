// Additional JavaScript for Google Sheets-like functionality

$(document).ready(function () {
    // Initialize DataTables if needed
    if ($.fn.DataTable) {
        $('.datatable').DataTable({
            pageLength: 25,
            responsive: true
        });
    }

    // Keyboard shortcuts for Google Sheets-like navigation
    $(document).on('keydown', function (e) {
        // Ctrl/Cmd + F to focus search
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
            e.preventDefault();
            $('#subcategorySearch').focus();
        }

        // Enter to add item when search is focused
        if (e.key === 'Enter' && $('#subcategorySearch').is(':focus')) {
            addSelectedItem();
        }

        // Esc to clear search
        if (e.key === 'Escape') {
            clearSearch();
        }
    });

    // Auto-calculate when quantity changes
    $(document).on('input', '.quantity-input', function () {
        const row = $(this).closest('tr');
        const quantity = $(this).val();
        const unitPrice = parseFloat(row.find('td:nth-child(4)').text().replace('₹', ''));
        const gstPercent = parseFloat(row.find('td:nth-child(5)').text().replace('%', ''));

        if (!isNaN(quantity) && quantity > 0) {
            const basicAmount = unitPrice * quantity;
            const gstAmount = basicAmount * (gstPercent / 100);
            const lineTotal = basicAmount + gstAmount;

            row.find('td:nth-child(7)').text('₹' + basicAmount.toFixed(2));
            row.find('td:nth-child(8)').text('₹' + gstAmount.toFixed(2));
            row.find('td:nth-child(9)').html('<strong>₹' + lineTotal.toFixed(2) + '</strong>');

            // Update totals
            updateGrandTotal();
        }
    });

    // Function to update grand total
    function updateGrandTotal() {
        let subtotal = 0;
        let totalGst = 0;
        let grandTotal = 0;

        $('.table-sheet tbody tr').each(function () {
            const basicAmount = parseFloat($(this).find('td:nth-child(7)').text().replace('₹', '')) || 0;
            const gstAmount = parseFloat($(this).find('td:nth-child(8)').text().replace('₹', '')) || 0;

            subtotal += basicAmount;
            totalGst += gstAmount;
            grandTotal += basicAmount + gstAmount;
        });

        // Update footer
        $('tfoot td:nth-child(7)').text('₹' + subtotal.toFixed(2));
        $('tfoot td:nth-child(8)').text('₹' + totalGst.toFixed(2));
        $('tfoot td:nth-child(9)').html('<strong>₹' + grandTotal.toFixed(2) + '</strong>');

        // Check budget
        const approvedAmount = parseFloat($('.total-value').eq(0).text().replace('₹', '')) || 0;
        if (approvedAmount > 0) {
            const remainingBudget = approvedAmount - grandTotal;
            $('.total-value').eq(2).text('₹' + remainingBudget.toFixed(2));

            // Update warning colors
            if (remainingBudget < 0) {
                $('.total-box').eq(1).removeClass('bg-success').addClass('bg-danger');
                $('.total-box').eq(2).removeClass('bg-warning').addClass('bg-danger');
            } else {
                $('.total-box').eq(1).removeClass('bg-danger').addClass('bg-success');
                $('.total-box').eq(2).removeClass('bg-danger').addClass('bg-warning');
            }
        }
    }
});

// Copy to clipboard function
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(function () {
        showToast('Copied to clipboard!', 'success');
    }).catch(function (err) {
        console.error('Failed to copy: ', err);
    });
}

// Export to Excel (basic)
function exportToExcel() {
    let csv = [];
    let rows = document.querySelectorAll("table tr");

    for (let i = 0; i < rows.length; i++) {
        let row = [], cols = rows[i].querySelectorAll("td, th");

        for (let j = 0; j < cols.length; j++) {
            row.push(cols[j].innerText);
        }

        csv.push(row.join(","));
    }

    // Download CSV file
    let csvFile = new Blob([csv.join("\n")], { type: "text/csv" });
    let downloadLink = document.createElement("a");

    downloadLink.download = "purchase_order.csv";
    downloadLink.href = window.URL.createObjectURL(csvFile);
    downloadLink.style.display = "none";

    document.body.appendChild(downloadLink);
    downloadLink.click();
    document.body.removeChild(downloadLink);

    showToast('Exported to CSV!', 'success');
}