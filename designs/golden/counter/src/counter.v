`default_nettype none

module counter (
    input wire clk,
    input wire rst_n,
    input wire enable,
    input wire up,
    input wire load,
    input wire [7:0] load_value,
    output reg [7:0] count
);
    always @(posedge clk) begin
        if (!rst_n)
            count <= 8'd0;
        else if (load)
            count <= load_value;
        else if (enable) begin
            if (up)
                count <= count + 8'd1;
            else
                count <= count - 8'd1;
        end
    end
endmodule

`default_nettype wire
